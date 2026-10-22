from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from miles.auth.context import AuthContext, client_origin
from miles.auth.sessions import (
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
OIDC_SESSION_PATHS = frozenset({"/api/auth/me", "/api/auth/logout", "/api/auth/me/preferences"})

CallNext = Callable[[Request], Awaitable[Response]]


def _same_email(session_email: str | None, admin_email: str) -> bool:
    # Même règle qu'à la reconnaissance : égalité insensible à la casse, rien d'autre.
    return session_email is not None and session_email.lower() == admin_email.lower()


def _deny(code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


async def auth_gate(request: Request, call_next: CallNext) -> Response:
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
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
        if path not in OIDC_SESSION_PATHS:
            return _deny(status.HTTP_403_FORBIDDEN, "aucun_droit")
    # Recalculé à chaque requête, pas mémorisé : après une réinitialisation du
    # compte dans .env, les sessions de l'ancien administrateur ne valent plus rien.
    elif session.subject_kind != LOCAL_ADMIN_KIND or session.subject != account.username:
        await db_delete_session(ctx.db, session.digest)
        log.warning("session_revoquee_compte_change", origin=client_origin(request))
        return _deny(status.HTTP_401_UNAUTHORIZED, "session_requise")
    request.state.session = session
    return await call_next(request)
