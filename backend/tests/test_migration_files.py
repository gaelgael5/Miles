from __future__ import annotations

from pathlib import Path

import pytest

from miles.config import DEFAULT_MIGRATIONS_DIR
from miles.db.migration_files import MigrationError, file_load_migrations
from tests.conftest import write_migrations


def test_file_load_migrations_valid_dir_returns_sorted_with_checksums(tmp_path: Path) -> None:
    directory = write_migrations(
        tmp_path, {"0002_beta.sql": "SELECT 2;", "0001_alpha.sql": "SELECT 1;"}
    )

    migrations = file_load_migrations(directory)

    assert [(m.version, m.name) for m in migrations] == [(1, "alpha"), (2, "beta")]
    assert migrations[0].checksum != migrations[1].checksum
    assert len(migrations[0].checksum) == 64


def test_file_load_migrations_same_content_same_checksum(tmp_path: Path) -> None:
    first = file_load_migrations(write_migrations(tmp_path / "a", {"0001_x.sql": "SELECT 1;"}))
    second = file_load_migrations(write_migrations(tmp_path / "b", {"0001_y.sql": "SELECT 1;"}))

    assert first[0].checksum == second[0].checksum


def test_file_load_migrations_ignores_non_sql_files(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0001_alpha.sql": "SELECT 1;", "README.md": "doc"})

    assert [m.version for m in file_load_migrations(directory)] == [1]


@pytest.mark.parametrize("bad_name", ["1_alpha.sql", "0001-alpha.sql", "0001_Alpha.sql"])
def test_file_load_migrations_badly_named_sql_raises(tmp_path: Path, bad_name: str) -> None:
    directory = write_migrations(tmp_path, {"0001_ok.sql": "SELECT 1;", bad_name: "SELECT 2;"})

    with pytest.raises(MigrationError, match="nom de migration invalide"):
        file_load_migrations(directory)


def test_file_load_migrations_gap_raises(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0003_c.sql": "SELECT 3;"})

    with pytest.raises(MigrationError, match="non continue"):
        file_load_migrations(directory)


def test_file_load_migrations_duplicate_version_raises(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0001_a.sql": "SELECT 1;", "0001_b.sql": "SELECT 2;"})

    with pytest.raises(MigrationError, match="non continue"):
        file_load_migrations(directory)


def test_file_load_migrations_not_starting_at_one_raises(tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0002_b.sql": "SELECT 2;"})

    with pytest.raises(MigrationError, match="non continue"):
        file_load_migrations(directory)


def test_file_load_migrations_empty_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="aucune migration"):
        file_load_migrations(tmp_path)


def test_file_load_migrations_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="introuvable"):
        file_load_migrations(tmp_path / "absent")


def test_repository_migrations_are_loadable() -> None:
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)

    assert migrations[0].name == "socle"
