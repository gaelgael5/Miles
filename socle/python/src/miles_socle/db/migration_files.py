from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MIGRATION_FILE_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    """Incohérence entre les migrations du dépôt et celles de la base."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def file_load_migrations(directory: Path) -> list[Migration]:
    """Charge les migrations numérotées, triées, et vérifie que la suite est continue."""
    if not directory.is_dir():
        raise MigrationError(f"répertoire de migrations introuvable : {directory}")
    migrations = [_file_read_migration(path) for path in sorted(directory.glob("*.sql"))]
    if not migrations:
        raise MigrationError(f"aucune migration dans {directory}")
    _check_contiguous(migrations)
    return migrations


def _file_read_migration(path: Path) -> Migration:
    match = MIGRATION_FILE_RE.match(path.name)
    # Un .sql mal nommé est refusé plutôt qu'ignoré : l'ignorer laisserait croire
    # qu'une migration a été jouée alors qu'elle n'a jamais été vue.
    if match is None:
        raise MigrationError(f"nom de migration invalide : {path.name} (attendu NNNN_nom.sql)")
    sql = path.read_text(encoding="utf-8")
    return Migration(
        version=int(match["version"]),
        name=match["name"],
        sql=sql,
        checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
    )


def _check_contiguous(migrations: list[Migration]) -> None:
    versions = [m.version for m in migrations]
    expected = list(range(1, len(migrations) + 1))
    # Doublon ou trou = collision de numéros entre deux branches de travail :
    # on refuse plutôt que de jouer un ordre que personne n'a choisi.
    if versions != expected:
        raise MigrationError(f"numérotation non continue depuis 0001 : {versions}")
