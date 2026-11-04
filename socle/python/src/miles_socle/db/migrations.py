from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg
import structlog

from miles_socle.db.migration_files import Migration, MigrationError

log = structlog.get_logger(__name__)

# Clef arbitraire mais fixe : deux déploiements lancés en même temps ne doivent
# jamais jouer les mêmes migrations en parallèle.
MIGRATION_LOCK_KEY = 0x4D494C4553

if TYPE_CHECKING:
    from asyncpg.pool import PoolConnectionProxy

# Connexion directe (migrations) ou empruntée au pool (contrôle de santé). L'instruction
# `type` est évaluée paresseusement : les classes asyncpg ne sont génériques que dans les
# stubs, un alias évalué à l'import lèverait à l'exécution.
type DbConnection = asyncpg.Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record]

_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer     PRIMARY KEY,
    name       text        NOT NULL,
    checksum   text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


async def db_applied_checksums(conn: DbConnection) -> dict[int, str]:
    """Versions appliquées et leur empreinte ; vide si la table de suivi n'existe pas."""
    exists = await conn.fetchval("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
    if not exists:
        return {}
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {row["version"]: row["checksum"] for row in rows}


async def db_schema_version(conn: DbConnection) -> int | None:
    """Dernière version appliquée ; None si la base n'a jamais été migrée."""
    applied = await db_applied_checksums(conn)
    return max(applied) if applied else None


async def db_apply_migration(conn: DbConnection, migration: Migration) -> None:
    # Une migration et sa ligne de suivi dans la même transaction : un échec au
    # milieu ne laisse ni schéma à moitié posé, ni version annoncée à tort.
    async with conn.transaction():
        await conn.execute(migration.sql)
        await conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum) VALUES ($1, $2, $3)",
            migration.version,
            migration.name,
            migration.checksum,
        )


def resolve_pending(migrations: list[Migration], applied: dict[int, str]) -> list[Migration]:
    """Migrations à jouer ; lève si la base diverge du dépôt."""
    known = {m.version: m for m in migrations}
    unknown = sorted(set(applied) - set(known))
    if unknown:
        raise MigrationError(f"la base porte des versions absentes du dépôt : {unknown}")
    for version, checksum in applied.items():
        # Une migration appliquée est immuable : la modifier ferait diverger les bases
        # qui l'ont déjà jouée de celles qui la joueront.
        if known[version].checksum != checksum:
            raise MigrationError(f"migration {version:04d} modifiée après application")
    return [m for m in migrations if m.version not in applied]


async def resolve_apply_migrations(conn: DbConnection, migrations: list[Migration]) -> list[int]:
    """Joue les migrations manquantes sous verrou consultatif ; rend les versions jouées."""
    await conn.execute("SELECT pg_advisory_lock($1)", MIGRATION_LOCK_KEY)
    try:
        await conn.execute(_TRACKING_DDL)
        pending = resolve_pending(migrations, await db_applied_checksums(conn))
        for migration in pending:
            await db_apply_migration(conn, migration)
            log.info("migration_appliquee", version=migration.version, name=migration.name)
        return [m.version for m in pending]
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", MIGRATION_LOCK_KEY)
