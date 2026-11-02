from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.sessions import SESSION_COOKIE
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.probe import HealthReport
from miles_socle.pairing.api_peer import router as peer_router
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER
from miles_socle.signing.hosting import HOSTED_VERSION_PATH
from miles_socle.signing.protocol import PAIRING_REVOKED_PATH

from environnement.app import build_app
from environnement.event_types import code_event_types
from environnement.hosting.api_peer_hosting import router as peer_hosting_router
from environnement.identity.service import PEER_PING_PATH, IdentityService
from environnement.ingestion.api_ingest import INGEST_PATH

# Le `nginx.conf` DU PRODUIT : il reste au produit (décision du 28/10/2026), et c'est
# lui qui décide ce qui atteint le backend.
NGINX = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"


def _chemins() -> set[str]:
    """Les chemins servis, lus dans la spec OpenAPI.

    Et non dans `app.routes` : cette version de FastAPI y place des enveloppes de
    routeur inclus, sans attribut `path`. La spec est l'interface publique, elle ne
    dépend pas de la forme interne du routeur.
    """
    return set(build_app().openapi()["paths"])


class _NoSessionDb:
    """Base dont la table des sessions est vide : aucun jeton présenté n'y existe.

    C'est exactement l'état du produit vis-à-vis d'un cookie ouvert sur un AUTRE produit :
    les tables de sessions sont étanches, et aucun secret de session n'est partagé.
    """

    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def _identity_service(db: _NoSessionDb) -> IdentityService:
    """Le VRAI service, sur une base sans pair apparié : l'état d'un module jamais apparié.

    Une doublure du service aurait prouvé le comportement de la doublure. Ici, le refus
    vient du code qui refusera en production.
    """
    return IdentityService(
        pool=cast(Any, db),
        secrets=cast(Any, None),
        cipher=cast(Any, None),
        catalog=EventTypeCatalog(code_event_types()),
        now=lambda: datetime.now(UTC),
        http=cast(Any, None),
        origin=None,
    )


async def _sante() -> HealthReport:
    return HealthReport(database_reachable=True, schema_version=8, expected_schema_version=8)


def _app(account: AdminAccount | None, tmp_path: Path) -> FastAPI:
    app = build_app()
    db = _NoSessionDb()
    app.state.identity = _identity_service(db)
    # Posée par la durée de vie en vrai ; ici une sonde d'essai, pour que la route
    # réponde réellement au lieu d'être seulement déclarée.
    app.state.health_probe = _sante
    app.state.auth = AuthContext(
        store=AdminAccountStore(tmp_path / ".env", tmp_path / ".env.bak", account),
        db=db,
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=12),
        cookie_secure=True,
    )
    return app


@pytest.fixture
def client_sans_admin(tmp_path: Path) -> TestClient:
    return TestClient(_app(None, tmp_path))


@pytest.fixture
def client_avec_admin(admin_account: AdminAccount, tmp_path: Path) -> TestClient:
    return TestClient(_app(admin_account, tmp_path))


def test_la_sante_repond_sans_session(client_sans_admin: TestClient) -> None:
    # Le script de déploiement l'interroge avant toute session, sur une installation où
    # aucun administrateur n'existe encore.
    reponse = client_sans_admin.get("/api/health")

    assert reponse.status_code == 200
    assert reponse.json() == {
        "status": "ok",
        "database": "up",
        "schema_version": 8,
        "expected_schema_version": 8,
    }


def test_l_etat_d_amorcage_est_lisible_sans_session(client_sans_admin: TestClient) -> None:
    reponse = client_sans_admin.get("/api/bootstrap/status")

    assert reponse.status_code == 200
    assert reponse.json() == {"admin_declared": False}


def test_tant_qu_aucun_administrateur_n_existe_rien_d_autre_n_est_ouvert(
    client_sans_admin: TestClient,
) -> None:
    reponse = client_sans_admin.get("/api/cultures")

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "amorcage_requis"}


def test_une_route_sans_session_est_refusee(client_avec_admin: TestClient) -> None:
    reponse = client_avec_admin.get("/api/cultures")

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "session_requise"}


def test_un_cookie_de_session_d_un_autre_produit_est_refuse(
    client_avec_admin: TestClient,
) -> None:
    # Un jeton valide ailleurs n'a pas d'empreinte dans CETTE base : refusé.
    client_avec_admin.cookies.set(SESSION_COOKIE, "jeton-ouvert-sur-un-autre-produit")

    reponse = client_avec_admin.get("/api/cultures")

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "session_requise"}


@pytest.mark.parametrize(
    "chemin",
    [
        "/api/secrets",
        "/api/oidc/connectors",
        "/api/auth/me",
        "/api/auth/me/preferences",
    ],
)
def test_aucune_route_de_gestion_n_est_atteignable_sans_session(
    client_avec_admin: TestClient, chemin: str
) -> None:
    # Fail closed : la passerelle ne connaît qu'une liste blanche, et ces routes n'y sont pas.
    assert client_avec_admin.get(chemin).status_code == 401


def test_les_routes_du_socle_sont_toutes_montees() -> None:
    chemins = _chemins()

    # Le pendant de la garde « écran déclaré au routage mais absent du menu » : une route
    # oubliée ici donne un écran qui appelle dans le vide, sans que rien ne soit rouge.
    assert {
        "/api/health",
        "/api/bootstrap",
        "/api/bootstrap/status",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/me/preferences",
        "/api/auth/cultures",
        "/api/auth/oidc/connectors",
        "/api/auth/oidc/start",
        "/api/auth/oidc/callback",
        "/api/cultures",
        "/api/cultures/active",
        "/api/cultures/activation",
        "/api/secrets",
        "/api/secret-types",
        "/api/oidc/connectors",
    } <= chemins


def test_la_SEULE_route_hors_du_portillon_est_le_point_d_entree_d_ingestion() -> None:
    """La garde d'une famille neuve : une route hors de `/api` n'est gardée par PERSONNE.

    La passerelle d'authentification ne regarde que `/api` — c'est écrit dans sa première
    ligne. Toute route posée ailleurs est donc ouverte au réseau, et ne tient que par ce
    qu'elle vérifie elle-même. Le point d'entrée d'ingestion est dans ce cas, et c'est
    une décision : il est appelé de machine à machine, s'authentifie par clé d'API, et
    porte des paramètres de chemin que la liste blanche — qui compare des chemins exacts
    — ne saurait pas décrire.

    Cette égalité est écrite en dur exprès. Poser une seconde route hors de `/api` doit
    obliger quelqu'un à venir le dire ici, en écrivant par quoi elle est protégée. Sans
    cette garde, une route d'administration posée hors de `/api` par distraction serait
    ouverte à tous, et verte partout.
    """
    hors_portillon = {chemin for chemin in _chemins() if not chemin.startswith("/api/")}

    assert hors_portillon == {INGEST_PATH}


def test_toute_route_hors_de_l_API_est_RELAYEE_par_le_proxy() -> None:
    """La garde du défaut du 02/11/2026, que seule la livraison a révélé.

    Le `nginx.conf` du front est une **seconde déclaration de surface**, indépendante de
    celle de l'application : il relaie `/api/` au backend et sert tout le reste comme des
    fichiers statiques. Une route posée hors de `/api` tombe donc dans `location /`, où
    nginx refuse un POST par un **405 Not Allowed** — et le backend ne voit jamais la
    requête. Mesuré : le point d'entrée d'ingestion répondait 401 correctement en
    interne, et 405 sur le port publié.

    Aucun test ne pouvait le voir : tous montent l'application ASGI, aucun ne monte le
    proxy. Celui-ci lit le fichier de configuration, ce qui est la seule façon de
    confronter les deux déclarations sans déployer.
    """
    conf = NGINX.read_text(encoding="utf-8")
    blocs = {
        nom: corps for nom, corps in re.findall(r"location\s+(\S+)\s*\{([^}]*)\}", conf, re.DOTALL)
    }
    hors_api = {c for c in _chemins() if not c.startswith("/api/")}
    assert hors_api, "aucune route hors de /api : cette garde n'éprouverait rien"
    for chemin in hors_api:
        prefixe = f"/{chemin.split('/')[1]}/"
        assert prefixe in blocs, (
            f"{chemin} n'est relayée par aucun bloc nginx : le port publié rendra 405"
        )
        assert "proxy_pass" in blocs[prefixe], (
            f"le bloc nginx {prefixe} existe mais ne relaie rien au backend"
        )


def test_la_documentation_interactive_n_est_pas_servie() -> None:
    # /docs et /openapi.json seraient des routes ouvertes hors de la passerelle.
    app = build_app()

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert "/docs" not in _chemins()


def test_la_route_de_pair_est_declaree_au_portillon_depuis_son_propre_routeur() -> None:
    """La garde du ticket : chemin ouvert et vérification de signature viennent d'un seul lieu.

    Le portillon ne laisse passer que ce que `peer_router` porte. Si quelqu'un ouvrait un
    chemin à la main sans la route qui vérifie, cette égalité tomberait — et c'est
    exactement la panne qu'on refuse : une route ouverte à tous, verte partout.
    """
    app = build_app()

    assert app.state.signed_api_paths == frozenset(
        route.path
        for routeur in (peer_router, peer_hosting_router)
        for route in routeur.routes
        if isinstance(route, APIRoute)
    )
    # DEUX chemins ouverts depuis le 29/10/2026, et le second est le sens inverse du
    # premier : l'enrôlement nous POUSSE l'avis qu'il nous a révoqué l'accès. Cette
    # égalité est écrite en dur exprès — ouvrir un chemin de plus doit obliger quelqu'un
    # à venir le dire ici, plutôt que de passer inaperçu.
    # TROIS depuis le 01/11/2026 : l'enrôlement nous POUSSE l'ordre de servir une
    # version (story 3bbd4f87), et ce chemin-là écrit sur notre volume. La décision
    # que ce rouge force à prendre : il n'est ouvert que parce que la signature du
    # module d'enrôlement apparié y est vérifiée avant toute lecture du corps.
    assert app.state.signed_api_paths == {
        PEER_PING_PATH,
        PAIRING_REVOKED_PATH,
        HOSTED_VERSION_PATH,
    }


def test_les_routes_de_l_identite_exigent_une_session(client_avec_admin: TestClient) -> None:
    # Elles montrent la clé publique, déclarent le pair et DÉCLENCHENT l'appariement :
    # rien de tout cela n'est public. Une route d'appariement ouverte laisserait un
    # inconnu faire frapper ce module chez un enrôlement qu'il aurait choisi.
    assert client_avec_admin.get("/api/identity").status_code == 401
    assert client_avec_admin.get("/api/identity/peer").status_code == 401
    assert client_avec_admin.put("/api/identity/peer", json={}).status_code == 401
    assert client_avec_admin.post("/api/identity/peer/ping").status_code == 401
    assert client_avec_admin.get("/api/identity/pairing").status_code == 401
    assert client_avec_admin.post("/api/identity/pairing", json={}).status_code == 401
    assert client_avec_admin.post("/api/identity/pairing/confirm", json={}).status_code == 401
    assert client_avec_admin.delete("/api/identity/pairing").status_code == 401


def test_un_appel_de_pair_non_signe_est_refuse(client_avec_admin: TestClient) -> None:
    # La route passe le portillon — elle est faite pour être appelée sans session — et
    # c'est ELLE qui refuse. Sans pair apparié, il n'y a même pas de clé pour vérifier.
    reponse = client_avec_admin.post(PEER_PING_PATH, json={})

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "signature_refusee"}


def test_le_refus_d_un_appel_de_pair_ne_dit_pas_ce_qui_peche(
    client_avec_admin: TestClient,
) -> None:
    # Dire si c'est l'en-tête, l'origine ou la signature offrirait un oracle pour
    # approcher l'une par l'autre. La raison précise va au journal, pas à l'appelant.
    refus = {
        client_avec_admin.post(PEER_PING_PATH, json={}, headers=entetes).json()["detail"]
        for entetes in (
            {},
            {ORIGIN_HEADER: "https://enrolement.test"},
            {ORIGIN_HEADER: "https://enrolement.test", SIGNATURE_HEADER: "v1 " + "A" * 86},
            {ORIGIN_HEADER: "pas-une-origine", SIGNATURE_HEADER: "v1 " + "A" * 86},
        )
    }

    assert refus == {"signature_refusee"}


def test_les_routes_de_l_identite_sont_montees() -> None:
    chemins = _chemins()

    assert {
        "/api/identity",
        "/api/identity/peer",
        "/api/identity/peer/ping",
        PEER_PING_PATH,
    } <= chemins
