from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from miles import app as app_module
from miles.auth.admin_account import AdminConfigError
from miles.db.migration_files import MigrationError
from tests.auth_fixtures import BASE_ENV, write_env
from tests.conftest import FakeConnection, write_migrations


class _FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})
    monkeypatch.setenv("MILES_DATABASE_URL", "postgresql://miles:x@db:5432/miles")
    monkeypatch.setenv("MILES_MIGRATIONS_DIR", str(directory))
    _set_env_files(monkeypatch, tmp_path / "files")
    return directory


def _set_env_files(
    monkeypatch: pytest.MonkeyPatch, directory: Path, content: str = BASE_ENV
) -> None:
    directory.mkdir()
    env_file, backup = write_env(directory, content)
    monkeypatch.setenv("MILES_ENV_FILE", str(env_file))
    monkeypatch.setenv("MILES_ENV_BACKUP_FILE", str(backup))
    monkeypatch.setenv("MILES_MQTT_HOST", "mqtt")
    monkeypatch.setenv("MILES_MQTT_PASSWORD", "x")
    monkeypatch.setattr(app_module, "run_responder", _idle_responder)


RESPONDERS: list[Any] = []


async def _idle_responder(settings: Any, handlers: Any) -> None:
    # Doublure : pas de broker en test unitaire ; on vérifie seulement le branchement.
    RESPONDERS.append((settings, handlers))
    await asyncio.Event().wait()


def test_create_app_lifespan_wires_probe_with_expected_version(
    monkeypatch: pytest.MonkeyPatch, env: Path
) -> None:
    pool = _FakePool()

    async def fake_pool(settings: Any) -> _FakePool:
        return pool

    monkeypatch.setattr(app_module, "db_create_pool", fake_pool)
    application = app_module.create_app()

    with TestClient(application):
        probe = application.state.health_probe
        assert probe.args[0] is pool
        assert probe.args[1] == 2
        assert application.state.auth.db is pool
        assert application.state.auth.store.account is None
        settings, handlers = RESPONDERS[-1]
        assert (settings.host, settings.port, settings.username) == ("mqtt", 1883, "miles-backend")
        assert "system.ping" in handlers

    assert pool.closed is True


def test_create_app_health_route_reports_schema_behind(
    monkeypatch: pytest.MonkeyPatch, env: Path
) -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}])

    class _Pool(_FakePool):
        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[FakeConnection]:
            yield conn

    async def fake_pool(settings: Any) -> _Pool:
        return _Pool()

    monkeypatch.setattr(app_module, "db_create_pool", fake_pool)

    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["expected_schema_version"] == 2


def test_create_app_without_migrations_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MILES_DATABASE_URL", "postgresql://miles:x@db:5432/miles")
    monkeypatch.setenv("MILES_MIGRATIONS_DIR", str(tmp_path / "absent"))
    _set_env_files(monkeypatch, tmp_path / "files")

    with pytest.raises(MigrationError):
        app_module.create_app()


def test_create_app_partial_admin_account_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = write_migrations(tmp_path / "m", {"0001_a.sql": "SELECT 1;"})
    monkeypatch.setenv("MILES_DATABASE_URL", "postgresql://miles:x@db:5432/miles")
    monkeypatch.setenv("MILES_MIGRATIONS_DIR", str(directory))
    _set_env_files(monkeypatch, tmp_path / "files", BASE_ENV + "MILES_ADMIN_USERNAME='admin'\n")

    with pytest.raises(AdminConfigError):
        app_module.create_app()
