from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.db.migration_files import Migration, file_load_migrations
from miles_socle.testing import FakeConnection, write_migrations

# Réexportées depuis le socle pour les tests qui les prennent dans conftest.
__all__ = ["FakeConnection", "write_migrations"]


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def two_migrations(tmp_path: Path) -> list[Migration]:
    directory = write_migrations(
        tmp_path / "migrations",
        {"0001_alpha.sql": "CREATE TABLE alpha (id int);", "0002_beta.sql": "SELECT 2;"},
    )
    return file_load_migrations(directory)
