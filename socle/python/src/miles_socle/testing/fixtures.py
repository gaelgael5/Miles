"""Fixtures pytest communes aux suites unitaires des trois produits.

Importées dans le `conftest.py` du produit — `from miles_socle.testing.fixtures import
env_files` — ce qui suffit à pytest pour les enregistrer. Elles n'ont rien de spécifique à
un produit ; celles qui portent une identité (le compte d'amorçage et son adresse, la
configuration du produit) restent chez lui, parce qu'elles disent qui il est.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from miles_socle.db.migration_files import Migration, file_load_migrations
from miles_socle.testing.doubles import FakeConnection
from miles_socle.testing.files import write_env, write_migrations


@pytest.fixture
def env_files(tmp_path: Path) -> tuple[Path, Path]:
    """Le `.env` de l'hôte et sa sauvegarde, que chaque produit monte fichier par fichier.

    Vides : ces tests éprouvent la lecture de la configuration, pas l'amorçage. Les droits
    600 sont posés quand même, pour que les tests tournent sur les mêmes fichiers que la
    machine — un test qui réussirait sur des droits plus larges ne prouverait pas le cas réel.
    """
    return write_env(tmp_path, "")


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def two_migrations(tmp_path: Path) -> list[Migration]:
    """Deux migrations sur disque : le minimum pour éprouver l'ordre et le rejeu."""
    directory = write_migrations(
        tmp_path / "migrations",
        {"0001_alpha.sql": "CREATE TABLE alpha (id int);", "0002_beta.sql": "SELECT 2;"},
    )
    return file_load_migrations(directory)
