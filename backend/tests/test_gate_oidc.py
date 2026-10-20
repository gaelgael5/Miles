from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from miles.app import build_app
from miles.auth.admin_store import AdminAccountStore
from miles.auth.context import AuthContext
from miles.auth.passwords import hash_password
from miles.auth.sessions import OIDC_KIND, SESSION_COOKIE, db_create_session, new_session_token
from miles.auth.throttle import LoginThrottle
from tests.auth_fixtures import ADMIN_PASSWORD, BASE_ENV, FakeClock, FakeSessionDb, write_env

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path, root_admin: bool = False, email: str | None = None) -> TestClient:
    env, backup = write_env(
        tmp_path,
        BASE_ENV
        + "MILES_ADMIN_EMAIL='admin@miles.invalid'\nMILES_ADMIN_USERNAME='admin'\n"
        + f"MILES_ADMIN_PASSWORD_HASH='{hash_password(ADMIN_PASSWORD)}'\n",
    )
    db = FakeSessionDb()
    app = build_app()
    app.state.auth = AuthContext(
        store=AdminAccountStore.file_load(env, backup),
        db=db,
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=1),
        cookie_secure=False,
        now=FakeClock(NOW),
    )
    token, digest = new_session_token()
    asyncio.run(
        db_create_session(
            db,
            digest,
            OIDC_KIND,
            "alice-sub",
            NOW + timedelta(hours=1),
            "kc",
            "Alice",
            email,
            root_admin,
        )
    )
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    return client


@pytest.fixture
def oidc_client(tmp_path: Path) -> TestClient:
    return _client(tmp_path)


def test_recognised_admin_session_reaches_administration_routes(tmp_path: Path) -> None:
    client = _client(tmp_path, root_admin=True, email="ADMIN@miles.invalid")

    assert client.get("/api/secret-types").status_code == 200
    assert client.get("/api/auth/me").json()["root_admin"] is True


def test_recognised_admin_session_is_revoked_once_the_admin_email_changes(
    tmp_path: Path,
) -> None:
    # Session reconnue pour une adresse qui n'est plus celle du compte d'amorçage.
    client = _client(tmp_path, root_admin=True, email="ancien@miles.invalid")

    assert client.get("/api/secret-types").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_oidc_session_sees_itself_connected(oidc_client: TestClient) -> None:
    me = oidc_client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json() == {
        "kind": "oidc",
        "username": "Alice",
        "email": None,
        "directory": "kc",
        "root_admin": False,
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/secrets"),
        ("POST", "/api/secrets"),
        ("GET", "/api/secret-types"),
        ("GET", "/api/cultures"),
        ("POST", "/api/cultures/activation"),
        ("GET", "/api/oidc/connectors"),
        ("POST", "/api/oidc/connectors"),
        ("GET", "/api/security-services"),
        ("POST", "/api/security-services/racine/verification"),
    ],
)
def test_oidc_session_without_roles_reaches_no_protected_route(
    oidc_client: TestClient, method: str, path: str
) -> None:
    # Aucun accès par défaut : authentifié n'est pas autorisé tant que les rôles manquent.
    response = oidc_client.request(method, path, json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "aucun_droit"}


def test_oidc_session_can_sign_out(oidc_client: TestClient) -> None:
    assert oidc_client.post("/api/auth/logout").status_code == 204
    assert oidc_client.get("/api/auth/me").status_code == 401
