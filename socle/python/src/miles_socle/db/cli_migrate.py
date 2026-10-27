from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import structlog

from miles_socle.db.migration_files import MigrationError, file_load_migrations
from miles_socle.db.migrations import db_schema_version, resolve_apply_migrations
from miles_socle.db.pool import DatabaseAccess, db_connect
from miles_socle.log_config import configure_logging

log = structlog.get_logger(__name__)

EXIT_OK = 0
EXIT_MIGRATION_ERROR = 2
EXIT_SCHEMA_BEHIND = 3


class MigrateSettings(DatabaseAccess, Protocol):
    """Ce dont la migration a besoin en plus de l'accès à la base.

    Comme pour le pool, le socle ne connaît que la FORME de la configuration : chaque
    produit garde sa propre classe, avec ses défauts et son répertoire de migrations —
    le socle ne porte aucun SQL (décision du 27/10/2026).
    """

    @property
    def migrations_dir(self) -> Path: ...

    @property
    def log_level(self) -> str: ...


async def resolve_apply(settings: MigrateSettings) -> int:
    migrations = file_load_migrations(settings.migrations_dir)
    conn = await db_connect(settings)
    try:
        applied = await resolve_apply_migrations(conn, migrations)
    finally:
        await conn.close()
    log.info("migrations_terminees", appliquees=applied, version=migrations[-1].version)
    return EXIT_OK


async def resolve_status(settings: MigrateSettings) -> int:
    expected = file_load_migrations(settings.migrations_dir)[-1].version
    conn = await db_connect(settings)
    try:
        current = await db_schema_version(conn)
    finally:
        await conn.close()
    # Code de sortie distinct : le déploiement refuse de se déclarer bon sur un
    # schéma en retard, même si la commande de migration a « réussi ».
    if current != expected:
        log.error("schema_en_retard", version=current, attendue=expected)
        return EXIT_SCHEMA_BEHIND
    log.info("schema_a_jour", version=current)
    return EXIT_OK


def build_main(lire_configuration: Callable[[], MigrateSettings]) -> Callable[[], None]:
    """Fabrique le point d'entrée `<produit>-migrate` d'un produit.

    La configuration arrive par une fabrique et non par une classe importée : le socle
    ne doit dépendre d'aucun produit, et c'est le produit qui sait quel préfixe
    d'environnement lire et où sont ses migrations. Le nom du programme vient d'argparse,
    qui prend par défaut celui de la commande réellement appelée.
    """

    def main() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["apply", "status"])
        args = parser.parse_args()
        settings = lire_configuration()
        configure_logging(settings.log_level)
        command = resolve_apply if args.action == "apply" else resolve_status
        try:
            sys.exit(asyncio.run(command(settings)))
        except MigrationError as exc:
            log.error("migration_refusee", raison=str(exc))
            sys.exit(EXIT_MIGRATION_ERROR)

    return main
