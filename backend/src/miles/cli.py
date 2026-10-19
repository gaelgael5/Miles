from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from miles.config import DatabaseSettings
from miles.db.migration_files import MigrationError, file_load_migrations
from miles.db.migrations import db_schema_version, resolve_apply_migrations
from miles.db.pool import db_connect
from miles.log_config import configure_logging

log = structlog.get_logger(__name__)

EXIT_OK = 0
EXIT_MIGRATION_ERROR = 2
EXIT_SCHEMA_BEHIND = 3


async def _apply(settings: DatabaseSettings) -> int:
    migrations = file_load_migrations(settings.migrations_dir)
    conn = await db_connect(settings)
    try:
        applied = await resolve_apply_migrations(conn, migrations)
    finally:
        await conn.close()
    log.info("migrations_terminees", appliquees=applied, version=migrations[-1].version)
    return EXIT_OK


async def _status(settings: DatabaseSettings) -> int:
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="miles-migrate")
    parser.add_argument("action", choices=["apply", "status"])
    args = parser.parse_args()
    settings = DatabaseSettings()  # type: ignore[call-arg]  # valeurs lues dans l'environnement
    configure_logging(settings.log_level)
    command = _apply if args.action == "apply" else _status
    try:
        sys.exit(asyncio.run(command(settings)))
    except MigrationError as exc:
        log.error("migration_refusee", raison=str(exc))
        sys.exit(EXIT_MIGRATION_ERROR)
