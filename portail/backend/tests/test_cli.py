from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from miles import cli
from miles.config import DatabaseSettings
from tests.conftest import FakeConnection, write_migrations

DSN = "postgresql://miles:x@db:5432/miles"


def _settings(migrations_dir: Path) -> DatabaseSettings:
    return DatabaseSettings(database_url=DSN, migrations_dir=migrations_dir)  # type: ignore[arg-type]


def _patch_connect(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> list[bool]:
    closed: list[bool] = []

    async def fake_connect(settings: DatabaseSettings) -> Any:
        async def close() -> None:
            closed.append(True)

        conn.close = close  # type: ignore[attr-defined]
        return conn

    monkeypatch.setattr(cli, "db_connect", fake_connect)
    return closed


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    return write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})


async def test_status_schema_up_to_date_returns_ok(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}, {"version": 2, "checksum": "b"}])
    closed = _patch_connect(monkeypatch, conn)

    assert await cli._status(_settings(migrations_dir)) == cli.EXIT_OK
    assert closed == [True]


async def test_status_schema_behind_returns_dedicated_code(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}])
    _patch_connect(monkeypatch, conn)

    assert await cli._status(_settings(migrations_dir)) == cli.EXIT_SCHEMA_BEHIND


async def test_status_never_migrated_returns_dedicated_code(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    _patch_connect(monkeypatch, FakeConnection(table_exists=False))

    assert await cli._status(_settings(migrations_dir)) == cli.EXIT_SCHEMA_BEHIND


async def test_apply_blank_base_applies_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(table_exists=False)
    closed = _patch_connect(monkeypatch, conn)

    assert await cli._apply(_settings(migrations_dir)) == cli.EXIT_OK
    assert [args[0] for q, args in conn.executed if q.startswith("INSERT")] == [1, 2]
    assert closed == [True]


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["miles-migrate", *argv])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


def test_main_invalid_migrations_returns_migration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MILES_DATABASE_URL", DSN)
    monkeypatch.setenv("MILES_MIGRATIONS_DIR", str(tmp_path / "absent"))

    assert _run_main(monkeypatch, "status") == cli.EXIT_MIGRATION_ERROR


def test_main_status_dispatches_to_status(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    monkeypatch.setenv("MILES_DATABASE_URL", DSN)
    monkeypatch.setenv("MILES_MIGRATIONS_DIR", str(migrations_dir))
    _patch_connect(monkeypatch, FakeConnection(table_exists=False))

    assert _run_main(monkeypatch, "status") == cli.EXIT_SCHEMA_BEHIND


def test_main_unknown_action_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_main(monkeypatch, "drop") == 2
