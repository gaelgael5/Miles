from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest
from miles_socle.db.migration_files import MigrationError, file_load_migrations
from miles_socle.db.migrations import db_schema_version, resolve_apply_migrations

from miles.config import DEFAULT_MIGRATIONS_DIR
from miles.health import resolve_health
from tests.conftest import write_migrations

pytestmark = pytest.mark.integration


async def test_repository_migrations_apply_on_blank_base_then_rerun_is_noop(
    blank_db: str,
) -> None:
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)
    conn = await asyncpg.connect(blank_db)
    try:
        first = await resolve_apply_migrations(conn, migrations)
        second = await resolve_apply_migrations(conn, migrations)
        version = await db_schema_version(conn)
    finally:
        await conn.close()

    assert first == [m.version for m in migrations]
    assert second == []
    assert version == migrations[-1].version


async def test_migration_0001_sets_database_timezone_utc(blank_db: str) -> None:
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
    finally:
        await conn.close()
    # Le réglage s'applique aux nouvelles sessions : on vérifie sur une connexion neuve.
    fresh = await asyncpg.connect(blank_db)
    try:
        assert await fresh.fetchval("SHOW timezone") == "UTC"
    finally:
        await fresh.close()


async def test_new_migration_applies_on_existing_base(blank_db: str, tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0001_a.sql": "CREATE TABLE a (id int);"})
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(directory))
        write_migrations(directory, {"0002_b.sql": "ALTER TABLE a ADD COLUMN label text;"})
        applied = await resolve_apply_migrations(conn, file_load_migrations(directory))
        columns = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'a'"
        )
    finally:
        await conn.close()

    assert applied == [2]
    assert columns == 2


async def test_modified_applied_migration_is_refused(blank_db: str, tmp_path: Path) -> None:
    directory = write_migrations(tmp_path, {"0001_a.sql": "CREATE TABLE a (id int);"})
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(directory))
        write_migrations(directory, {"0001_a.sql": "CREATE TABLE a (id bigint);"})
        with pytest.raises(MigrationError, match="modifiée"):
            await resolve_apply_migrations(conn, file_load_migrations(directory))
    finally:
        await conn.close()


async def test_failing_migration_leaves_no_trace(blank_db: str, tmp_path: Path) -> None:
    directory = write_migrations(
        tmp_path,
        {"0001_a.sql": "CREATE TABLE a (id int);", "0002_b.sql": "CREATE TABLE b (; -- invalide"},
    )
    conn = await asyncpg.connect(blank_db)
    try:
        with pytest.raises(asyncpg.PostgresSyntaxError):
            await resolve_apply_migrations(conn, file_load_migrations(directory))
        version = await db_schema_version(conn)
        b_exists = await conn.fetchval("SELECT to_regclass('public.b') IS NOT NULL")
    finally:
        await conn.close()

    assert version == 1
    assert b_exists is False


async def test_resolve_health_real_base_behind_then_up_to_date(blank_db: str) -> None:
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)
    expected = migrations[-1].version
    pool = await asyncpg.create_pool(blank_db, min_size=1, max_size=2)
    try:
        before = await resolve_health(pool, expected, timeout_s=5.0)
        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, migrations)
        after = await resolve_health(pool, expected, timeout_s=5.0)
    finally:
        await pool.close()

    assert before.database_reachable and not before.healthy
    assert after.healthy
