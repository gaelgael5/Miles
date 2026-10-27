from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from miles_socle.db import cli_migrate
from miles_socle.testing import FakeConnection, write_migrations

DSN = "postgresql://miles:x@db:5432/miles"


@dataclass(frozen=True)
class Settings:
    """Configuration d'essai : la FORME qu'attend le socle, sans aucun produit.

    Le socle ne connaît que ce protocole ; chaque produit y répond avec sa propre classe,
    son préfixe d'environnement et son répertoire de migrations.
    """

    migrations_dir: Path
    database_url: SecretStr = field(default_factory=lambda: SecretStr(DSN))
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_connect_timeout_s: float = 5.0
    log_level: str = "info"


def _settings(migrations_dir: Path) -> Settings:
    return Settings(migrations_dir=migrations_dir)


def _patch_connect(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> list[bool]:
    closed: list[bool] = []

    async def fake_connect(settings: Settings) -> Any:
        async def close() -> None:
            closed.append(True)

        conn.close = close  # type: ignore[attr-defined]
        return conn

    monkeypatch.setattr(cli_migrate, "db_connect", fake_connect)
    return closed


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    return write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"})


async def test_status_schema_up_to_date_returns_ok(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}, {"version": 2, "checksum": "b"}])
    closed = _patch_connect(monkeypatch, conn)

    assert await cli_migrate.resolve_status(_settings(migrations_dir)) == cli_migrate.EXIT_OK
    assert closed == [True]


async def test_status_schema_behind_returns_dedicated_code(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}])
    _patch_connect(monkeypatch, conn)

    assert (
        await cli_migrate.resolve_status(_settings(migrations_dir))
        == cli_migrate.EXIT_SCHEMA_BEHIND
    )


async def test_status_never_migrated_returns_dedicated_code(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    _patch_connect(monkeypatch, FakeConnection(table_exists=False))

    assert (
        await cli_migrate.resolve_status(_settings(migrations_dir))
        == cli_migrate.EXIT_SCHEMA_BEHIND
    )


async def test_apply_blank_base_applies_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    conn = FakeConnection(table_exists=False)
    closed = _patch_connect(monkeypatch, conn)

    assert await cli_migrate.resolve_apply(_settings(migrations_dir)) == cli_migrate.EXIT_OK
    assert [args[0] for q, args in conn.executed if q.startswith("INSERT")] == [1, 2]
    assert closed == [True]


def _run_main(monkeypatch: pytest.MonkeyPatch, settings: Settings, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["produit-migrate", *argv])
    main = cli_migrate.build_main(lambda: settings)
    with pytest.raises(SystemExit) as exit_info:
        main()
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


def test_main_invalid_migrations_returns_migration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = _run_main(monkeypatch, _settings(tmp_path / "absent"), "status")

    assert code == cli_migrate.EXIT_MIGRATION_ERROR


def test_main_status_dispatches_to_status(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    _patch_connect(monkeypatch, FakeConnection(table_exists=False))

    code = _run_main(monkeypatch, _settings(migrations_dir), "status")

    assert code == cli_migrate.EXIT_SCHEMA_BEHIND


def test_main_unknown_action_is_rejected(
    monkeypatch: pytest.MonkeyPatch, migrations_dir: Path
) -> None:
    assert _run_main(monkeypatch, _settings(migrations_dir), "drop") == 2
