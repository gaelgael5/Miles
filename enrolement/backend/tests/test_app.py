from __future__ import annotations

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
from miles_socle.signing.calls import ORIGIN_HEADER
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PEER_PING_PATH,
)

from enrolement.app import build_app
from enrolement.event_types import code_event_types
from enrolement.pairing.api_peer import router as peer_router
from enrolement.pairing.service import PairingService


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


async def _sante() -> HealthReport:
    return HealthReport(database_reachable=True, schema_version=7, expected_schema_version=7)


def _pairing_service(db: Any) -> PairingService:
    """Le VRAI service, sur une base qui ne rend rien.

    Une doublure du service ne dirait que ce qu'on lui fait dire ; ici c'est le code de
    production qui refuse. Et les refus éprouvés plus bas n'atteignent jamais la base :
    ils se décident sur l'absence de signature, bien avant toute lecture.
    """
    return PairingService(
        pool=cast(Any, db),
        secrets=cast(Any, None),
        cipher=cast(Any, None),
        catalog=EventTypeCatalog(code_event_types()),
        now=lambda: datetime.now(UTC),
        origin=None,
        # Aucun appel sortant n'est émis par les refus éprouvés ici : ils se décident sur
        # l'absence de signature, bien avant toute lecture et bien avant tout envoi.
        http=cast(Any, None),
        request_ttl_s=3600,
    )


def _app(account: AdminAccount | None, tmp_path: Path) -> FastAPI:
    app = build_app()
    app.state.pairing = _pairing_service(_NoSessionDb())
    # Posée par la durée de vie en vrai ; ici une sonde d'essai, pour que la route
    # réponde réellement au lieu d'être seulement déclarée.
    app.state.health_probe = _sante
    app.state.auth = AuthContext(
        store=AdminAccountStore(tmp_path / ".env", tmp_path / ".env.bak", account),
        db=_NoSessionDb(),
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
        "schema_version": 7,
        "expected_schema_version": 7,
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


def test_la_documentation_interactive_n_est_pas_servie() -> None:
    # /docs et /openapi.json seraient des routes ouvertes hors de la passerelle.
    app = build_app()

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert "/docs" not in _chemins()


def test_seules_les_routes_de_pair_echappent_a_la_session() -> None:
    """La liste blanche des chemins signés est DÉRIVÉE du routeur qui les porte.

    Cette garde vérifie les deux moitiés : que la dérivation donne bien ce que le routeur
    porte, et que ce routeur ne porte QUE les trois routes du protocole. Sans la seconde,
    une route d'administration glissée dans ce routeur serait ouverte à tous — et la
    première assertion resterait verte.
    """
    app = build_app()

    assert app.state.signed_api_paths == frozenset(
        route.path for route in peer_router.routes if isinstance(route, APIRoute)
    )
    assert app.state.signed_api_paths == {
        PEER_PING_PATH,
        PAIRING_REQUEST_PATH,
        PAIRING_CONFIRM_PATH,
        PAIRING_STATUS_PATH,
    }


@pytest.mark.parametrize(
    "chemin", ["/api/pairing/requests", "/api/pairing/peers", "/api/pairing/identity"]
)
def test_les_routes_d_administration_de_l_appariement_exigent_une_session(
    client_avec_admin: TestClient, chemin: str
) -> None:
    # Elles listent les demandes et RENDENT LE CODE : les ouvrir donnerait à un inconnu
    # de quoi s'apparier sans qu'aucun humain ne l'ait voulu.
    assert client_avec_admin.get(chemin).status_code == 401


@pytest.mark.parametrize(
    ("chemin", "corps"),
    [
        (PEER_PING_PATH, {}),
        (PAIRING_REQUEST_PATH, {"public_key": "A" * 43, "name": "Recette"}),
        (PAIRING_CONFIRM_PATH, {"code": "123456"}),
        (PAIRING_STATUS_PATH, {}),
    ],
)
def test_un_appel_de_pair_non_signe_est_refuse_par_la_route(
    client_avec_admin: TestClient, chemin: str, corps: dict[str, str]
) -> None:
    # Ces routes passent le portillon — elles sont faites pour être appelées sans session
    # — et ce sont ELLES qui refusent. Le détail distingue le refus de la route de celui
    # du portillon (« session_requise »), sans quoi on ne saurait pas laquelle a parlé.
    #
    # L'appel est VALIDE partout ailleurs : corps bien formé, origine bien formée. Sans
    # cette précaution le test resterait vert pour la mauvaise raison — mesuré le
    # 28/10/2026 en retirant pour de vrai le contrôle de signature : l'absence d'origine
    # faisait refuser à sa place, et la garde ne prouvait que « quelque chose refuse ».
    #
    # CE QUE CE TEST NE PROUVE PAS, et il ne faut pas le lui faire dire : que la SIGNATURE
    # est vérifiée. La base est une doublure qui ne rend rien, donc plusieurs couches
    # refusent avant la cryptographie, et neutraliser le vérificateur laisse ce test vert.
    # La vérification elle-même est gardée par `tests/integration/test_appariement_pg.py`,
    # éprouvé en la neutralisant pour de vrai sur machine de test : trois tests rouges.
    reponse = client_avec_admin.post(
        chemin, json=corps, headers={ORIGIN_HEADER: "https://environnement.test"}
    )

    assert reponse.status_code == 401
    assert reponse.json()["detail"] != "session_requise"
