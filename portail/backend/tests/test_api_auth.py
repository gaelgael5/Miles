from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.sessions import SESSION_COOKIE
from miles_socle.auth.throttle import LoginThrottle

from miles.app import build_app
from tests.auth_fixtures import ADMIN_PASSWORD, BASE_ENV, FakeClock, FakeSessionDb, write_env

START = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
BOOTSTRAP = {"email": "gael@example.org", "username": "admin", "password": ADMIN_PASSWORD}


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.env, self.backup = write_env(tmp_path)
        self.db = FakeSessionDb()
        self.clock = FakeClock(START)
        self.app = build_app()
        self.reload()

    def reload(self) -> FastAPI:
        # Simule un redémarrage : le compte est relu dans .env, les sessions restent en base.
        self.app.state.auth = AuthContext(
            store=AdminAccountStore.file_load(self.env, self.backup),
            db=self.db,
            throttle=LoginThrottle(max_per_origin=3, max_global=100),
            session_ttl=timedelta(hours=1),
            cookie_secure=False,
            now=self.clock,
        )
        return self.app

    def client(self) -> TestClient:
        return TestClient(self.app)


@pytest.fixture
def harness(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


def _bootstrapped(harness: _Harness) -> TestClient:
    client = harness.client()
    assert client.post("/api/bootstrap", json=BOOTSTRAP).status_code == 201
    return client


def test_blank_install_reports_bootstrap_open_and_closes_protected_routes(
    harness: _Harness,
) -> None:
    client = harness.client()

    assert client.get("/api/bootstrap/status").json() == {"admin_declared": False}
    assert client.get("/api/auth/me").status_code == 403
    assert client.get("/api/auth/me").json() == {"detail": "amorcage_requis"}
    assert (
        client.post("/api/auth/login", json={"username": "a", "password": "b"}).status_code == 403
    )


def test_bootstrap_declares_account_logs_in_and_closes(harness: _Harness) -> None:
    client = harness.client()

    response = client.post("/api/bootstrap", json=BOOTSTRAP)

    assert response.status_code == 201
    assert response.json() == {
        "kind": "local_admin",
        "username": "admin",
        "subject": "admin",
        "email": BOOTSTRAP["email"],
        "directory": None,
        "root_admin": True,
    }
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Domain" not in cookie
    assert client.get("/api/auth/me").json()["username"] == "admin"
    assert client.get("/api/bootstrap/status").json() == {"admin_declared": True}
    assert ADMIN_PASSWORD not in harness.env.read_text(encoding="utf-8")


def test_bootstrap_after_declaration_is_refused_and_writes_nothing(harness: _Harness) -> None:
    _bootstrapped(harness)
    before = harness.env.read_bytes()

    other = {"email": "intrus@example.org", "username": "intrus", "password": ADMIN_PASSWORD}
    response = harness.client().post("/api/bootstrap", json=other)

    assert response.status_code == 409
    assert response.json() == {"detail": "amorcage_ferme"}
    assert harness.env.read_bytes() == before


def test_bootstrap_closed_after_restart(harness: _Harness) -> None:
    _bootstrapped(harness)
    harness.reload()

    response = harness.client().post("/api/bootstrap", json=BOOTSTRAP)

    assert response.status_code == 409


def test_bootstrap_weak_password_returns_rule_and_writes_nothing(harness: _Harness) -> None:
    response = harness.client().post("/api/bootstrap", json={**BOOTSTRAP, "password": "court"})

    assert response.status_code == 422
    assert response.json() == {"detail": {"rule": "min_length", "limit": 12}}
    assert harness.env.read_text(encoding="utf-8") == BASE_ENV


def test_bootstrap_invalid_username_names_field(harness: _Harness) -> None:
    response = harness.client().post("/api/bootstrap", json={**BOOTSTRAP, "username": "../x"})

    assert response.status_code == 422
    assert response.json() == {"detail": {"field": "username"}}


def test_bootstrap_unwritable_backup_returns_500_and_keeps_bootstrap_open(
    harness: _Harness,
) -> None:
    harness.backup.unlink()

    response = harness.client().post("/api/bootstrap", json=BOOTSTRAP)

    assert response.status_code == 500
    assert response.json() == {"detail": "env_ecriture_impossible"}
    assert harness.client().get("/api/bootstrap/status").json() == {"admin_declared": False}


def test_bootstrap_unknown_field_rejected(harness: _Harness) -> None:
    response = harness.client().post("/api/bootstrap", json={**BOOTSTRAP, "role": "root"})

    assert response.status_code == 422


def test_login_with_valid_credentials_opens_session(harness: _Harness) -> None:
    _bootstrapped(harness)
    client = harness.client()

    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    ("username", "password"), [("admin", "mauvais mot de passe"), ("autre", ADMIN_PASSWORD)]
)
def test_login_wrong_credentials_same_answer_whichever_is_wrong(
    harness: _Harness, username: str, password: str
) -> None:
    _bootstrapped(harness)

    response = harness.client().post(
        "/api/auth/login", json={"username": username, "password": password}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "identifiants_invalides"}
    assert SESSION_COOKIE not in response.cookies


def test_login_repeated_failures_are_throttled_even_with_right_password(
    harness: _Harness,
) -> None:
    _bootstrapped(harness)
    client = harness.client()
    for _ in range(3):
        client.post("/api/auth/login", json={"username": "admin", "password": "x" * 12})

    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 429


def test_protected_route_without_cookie_or_with_forged_cookie_is_refused(
    harness: _Harness,
) -> None:
    _bootstrapped(harness)
    client = harness.client()

    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, "forge")
    assert client.get("/api/auth/me").status_code == 401


def test_unknown_api_route_is_closed_by_default(harness: _Harness) -> None:
    client = _bootstrapped(harness)
    anonymous = harness.client()

    assert anonymous.get("/api/route-inexistante").status_code == 401
    assert client.get("/api/route-inexistante").status_code == 404


def test_session_expires_after_ttl(harness: _Harness) -> None:
    client = _bootstrapped(harness)

    harness.clock.current = START + timedelta(hours=1)

    assert client.get("/api/auth/me").status_code == 401


def test_session_of_reset_admin_is_revoked(harness: _Harness) -> None:
    client = _bootstrapped(harness)
    # Réinitialisation : on retire le compte de .env, puis un autre est déclaré.
    harness.env.write_text(BASE_ENV, encoding="utf-8")
    harness.reload()
    _bootstrapped_other = harness.client().post(
        "/api/bootstrap", json={**BOOTSTRAP, "username": "nouveau"}
    )
    assert _bootstrapped_other.status_code == 201

    assert client.get("/api/auth/me").status_code == 401
    assert len(harness.db.rows) == 1


def test_logout_deletes_session(harness: _Harness) -> None:
    client = _bootstrapped(harness)

    assert client.post("/api/auth/logout").status_code == 204

    assert harness.db.rows == {}
    assert client.get("/api/auth/me").status_code == 401


def test_docs_and_openapi_are_not_served(harness: _Harness) -> None:
    client = harness.client()

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
