from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.sessions import SESSION_COOKIE
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.health.probe import HealthReport

from enrolement.app import build_app


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


def _app(account: AdminAccount | None, tmp_path: Path) -> FastAPI:
    app = build_app()
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
