from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from functools import lru_cache

import structlog
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.routing import compile_path

from miles_socle.auth.context import AuthContext, client_origin
from miles_socle.auth.sessions import (
    LOCAL_ADMIN_KIND,
    OIDC_KIND,
    SESSION_COOKIE,
    db_delete_session,
    db_find_session,
    token_digest,
)

log = structlog.get_logger(__name__)

# Liste blanche : toute autre route /api exige une session. Une route ajoutée
# demain est donc fermée par défaut, sans que son auteur ait à y penser.
PUBLIC_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/bootstrap/status",
        "/api/bootstrap",
        "/api/auth/login",
        # Connexion OIDC : l'écran de connexion liste les connecteurs actifs, puis le
        # navigateur part chez le fournisseur et revient sans session.
        "/api/auth/oidc/connectors",
        "/api/auth/oidc/start",
        "/api/auth/oidc/callback",
        # Cultures actives, pour le sélecteur de l'écran de connexion (ticket 2dbfb065).
        "/api/auth/cultures",
    }
)
# Une session OIDC authentifie, elle n'autorise pas (ticket e9fc9b9b) : tant que les
# rôles n'existent pas, elle ne sert qu'à se voir connecté et à se déconnecter.
# Aucun accès par défaut : toute autre route lui est refusée.
# Les préférences (langue du portail) sont personnelles : les ouvrir n'atteint que la
# personne elle-même (ticket 0a52596d), et rien d'autre ne s'ouvre avec elles.
# Le GUID d'acteur (story 52ac5782) est de même nature : il ne désigne que la personne.
# Le consentement OAuth (story 9f09cd8b) aussi : une personne ne délègue que ses propres
# droits, recalculés par la route elle-même.
OIDC_SESSION_PATHS = frozenset(
    {
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/me/preferences",
        "/api/auth/me/identity",
        "/api/oauth/authorize",
        "/api/oauth/authorize/check",
    }
)
# Identité git personnelle (ticket 033e5ff3) : même raison, la personne n'y atteint que
# ses propres jetons. Préfixe, parce que la connexion git figure dans le chemin.
# Ses rangements (fd1eb7da) aussi : la route ne rend que les siens.
OIDC_SESSION_PREFIXES = (
    "/api/auth/me/git-identities",
    "/api/auth/me/oauth-grants",
    "/api/auth/me/shelves",
)


def _personal(path: str) -> bool:
    return path in OIDC_SESSION_PATHS or any(
        path == prefix or path.startswith(prefix + "/") for prefix in OIDC_SESSION_PREFIXES
    )


CallNext = Callable[[Request], Awaitable[Response]]


@lru_cache(maxsize=64)
def _matcher(template: str) -> re.Pattern[str]:
    """Le gabarit d'un chemin, compilé par la MÊME grammaire que le routeur.

    Compilé ici plutôt que cherché dans la table des routes : une version de FastAPI
    garde les routeurs inclus groupés derrière un objet privé, et un parcours de la
    table n'y voit aucune route — donc n'ouvre rien, en silence (mesuré sur 0.121).
    Un gabarit compilé est ancré, donc il n'ouvre jamais ce qu'on monterait dessous.
    """
    regex, _, _ = compile_path(template)
    return regex


def _public_route(request: Request) -> bool:
    """Cette requête tombe-t-elle sur une route que le produit a ouverte à tous ?"""
    ouvertes: frozenset[tuple[str, str]] = getattr(
        request.app.state, "public_api_routes", frozenset()
    )
    chemin = request.url.path
    return any(
        methode == request.method and _matcher(gabarit).match(chemin) is not None
        for methode, gabarit in ouvertes
    )


def _same_email(session_email: str | None, admin_email: str) -> bool:
    # Même règle qu'à la reconnaissance : égalité insensible à la casse, rien d'autre.
    return session_email is not None and session_email.lower() == admin_email.lower()


def _deny(code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


async def auth_gate(request: Request, call_next: CallNext) -> Response:
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
        return await call_next(request)
    # Routes authentifiées par SIGNATURE et non par session : appelées de machine à
    # machine, elles n'ont ni cookie ni humain derrière, et la route elle-même refuse un
    # appel non signé ou signé par une clé inconnue. Le portillon ne fait que lui laisser
    # la main. Trois propriétés, et aucune n'est accessoire :
    #   — le défaut est l'ensemble VIDE : un produit qui ne déclare rien n'ouvre rien ;
    #   — le produit déclare ces chemins DEPUIS le routeur qui les porte, de sorte que le
    #     chemin et sa vérification ne puissent pas se séparer — un chemin ouvert ici sans
    #     sa signature serait ouvert à tous ;
    #   — le passage précède le contrôle d'amorçage : un appel de pair ne dépend pas de
    #     l'existence d'un administrateur humain, et sa clé n'est connue que par appariement.
    if path in getattr(request.app.state, "signed_api_paths", frozenset()):
        return await call_next(request)
    # Routes authentifiées par un secret de STACK : un déclencheur d'hôte n'a ni cookie ni
    # personne derrière, et la route elle-même refuse tout si le secret n'est pas configuré
    # ou ne correspond pas. Les mêmes trois propriétés que ci-dessus, et une LISTE DISTINCTE
    # plutôt qu'une seule : une signature prouve l'identité d'un pair par une clé échangée à
    # l'appariement, un secret de stack ne prouve que l'appartenance à la stack. Les
    # confondre laisserait un chemin déclaré pour l'un s'ouvrir par le mécanisme de l'autre.
    if path in getattr(request.app.state, "system_api_paths", frozenset()):
        return await call_next(request)
    # Routes OUVERTES À TOUS, déclarées par le produit : un contrat d'interface se
    # pointe par une URL qu'un intégrateur ouvre sans compte (Gael, 05/11/2026). Les
    # mêmes trois propriétés que ci-dessus, et une liste encore distincte — ce qui est
    # ouvert à tous ne prouve rien du tout, et le confondre avec « authentifié par
    # signature » ouvrirait au monde une route qui n'attendait qu'un pair.
    #
    # Le chemin est comparé par ROUTAGE et non par égalité : ces routes portent des
    # paramètres (`/{source}`), et un préfixe ouvert aurait ouvert aussi ce qu'on
    # monterait dessous demain. La méthode compte dans la correspondance : ouvrir la
    # lecture d'un contrat n'ouvre pas son écriture.
    if _public_route(request):
        return await call_next(request)
    ctx: AuthContext = request.app.state.auth
    account = ctx.store.account
    if account is None:
        # Tant qu'aucun administrateur n'existe, seul l'amorçage est ouvert.
        return _deny(status.HTTP_403_FORBIDDEN, "amorcage_requis")
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _deny(status.HTTP_401_UNAUTHORIZED, "session_requise")
    session = await db_find_session(ctx.db, token_digest(token), ctx.now())
    if session is None:
        return _deny(status.HTTP_401_UNAUTHORIZED, "session_requise")
    if session.subject_kind == OIDC_KIND and session.root_admin:
        # Recalculé à chaque requête, comme pour le compte d'amorçage : si l'e-mail de
        # .env a changé, l'ancienne adresse ne donne plus rien, session ouverte ou non.
        if not _same_email(session.email, account.email):
            await db_delete_session(ctx.db, session.digest)
            log.warning("session_admin_oidc_revoquee", origin=client_origin(request))
            return _deny(status.HTTP_401_UNAUTHORIZED, "session_requise")
    elif session.subject_kind == OIDC_KIND:
        if not _personal(path):
            return _deny(status.HTTP_403_FORBIDDEN, "aucun_droit")
    # Recalculé à chaque requête, pas mémorisé : après une réinitialisation du
    # compte dans .env, les sessions de l'ancien administrateur ne valent plus rien.
    elif session.subject_kind != LOCAL_ADMIN_KIND or session.subject != account.username:
        await db_delete_session(ctx.db, session.digest)
        log.warning("session_revoquee_compte_change", origin=client_origin(request))
        return _deny(status.HTTP_401_UNAUTHORIZED, "session_requise")
    request.state.session = session
    return await call_next(request)
