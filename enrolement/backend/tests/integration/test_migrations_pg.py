from __future__ import annotations

import asyncpg
import pytest
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import db_schema_version, resolve_apply_migrations
from miles_socle.health.probe import resolve_health

from enrolement.config import DEFAULT_MIGRATIONS_DIR

pytestmark = pytest.mark.integration


async def test_les_migrations_passent_sur_une_base_vierge(blank_db: str) -> None:
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)
    conn = await asyncpg.connect(blank_db)
    try:
        applied = await resolve_apply_migrations(conn, migrations)

        assert applied == [m.version for m in migrations]
        assert await db_schema_version(conn) == migrations[-1].version
    finally:
        await conn.close()


async def test_rejouees_sur_une_base_deja_migree_elles_n_appliquent_rien(blank_db: str) -> None:
    # Le déploiement est rejouable : relancé après un échec partiel, il ne doit rien casser.
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, migrations)

        assert await resolve_apply_migrations(conn, migrations) == []
    finally:
        await conn.close()


async def test_les_tables_que_le_socle_interroge_existent_reellement(blank_db: str) -> None:
    """La preuve que le schéma du produit satisfait le socle, qui ne porte aucun SQL.

    Les noms sont vérifiés dans le test unitaire ; ici c'est PostgreSQL qui répond, donc
    les contraintes, les types et les références ont réellement été acceptés.
    """
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        tables = {
            row["tablename"]
            for row in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }

        assert {
            "events",
            "event_object_sequences",
            "event_objects",
            "cultures",
            "secrets",
            "secret_usages",
            "sessions",
            "oidc_connectors",
            "oidc_connector_labels",
            "oidc_login_attempts",
            "oidc_identities",
            "user_preferences",
            "schema_migrations",
        } <= tables
    finally:
        await conn.close()


async def test_la_base_refuse_de_desactiver_le_repli_en_us(blank_db: str) -> None:
    # Garde portée par la base, pas par le code : en-US est le repli de tout libellé.
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE cultures SET active = false WHERE code = 'en-US'")
    finally:
        await conn.close()


async def test_la_sante_est_degradee_tant_que_le_schema_est_en_retard(blank_db: str) -> None:
    attendue = file_load_migrations(DEFAULT_MIGRATIONS_DIR)[-1].version
    pool = await asyncpg.create_pool(blank_db, min_size=1, max_size=2)
    assert pool is not None
    try:
        # Servir avec un schéma incomplet est la panne silencieuse qu'un contrôle de
        # santé doit révéler : le déploiement lit ce verdict et refuse de se dire bon.
        avant = await resolve_health(pool, attendue, 5.0)
        assert avant.database_reachable
        assert not avant.healthy

        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))

        assert (await resolve_health(pool, attendue, 5.0)).healthy
    finally:
        await pool.close()
