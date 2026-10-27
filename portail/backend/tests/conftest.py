from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from miles.db.migration_files import Migration, file_load_migrations


class FakeConnection:
    """Doublure d'asyncpg.Connection : enregistre les requêtes, rejoue des réponses."""

    def __init__(self, *, table_exists: bool = True, rows: list[dict[str, Any]] | None = None):
        self.table_exists = table_exists
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_on: str | None = None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.table_exists

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return self.rows

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if self.fail_on is not None and self.fail_on in query:
            raise RuntimeError("échec simulé")
        return "OK"

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


def write_migrations(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


@pytest.fixture
def two_migrations(tmp_path: Path) -> list[Migration]:
    directory = write_migrations(
        tmp_path / "migrations",
        {"0001_alpha.sql": "CREATE TABLE alpha (id int);", "0002_beta.sql": "SELECT 2;"},
    )
    return file_load_migrations(directory)
