from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from miles.auth.sessions import db_create_session, db_delete_session, db_find_session
from miles.config import DEFAULT_MIGRATIONS_DIR
from miles.db.migration_files import file_load_migrations
from miles.db.migrations import resolve_apply_migrations

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


async def _migrated(dsn: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(dsn)
    await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
    return conn


async def test_sessions_create_find_expire_delete_on_real_base(blank_db: str) -> None:
    conn = await _migrated(blank_db)
    try:
        await db_create_session(conn, b"live", "local_admin", "admin", NOW + timedelta(hours=1))
        await db_create_session(conn, b"dead", "local_admin", "admin", NOW)

        found = await db_find_session(conn, b"live", NOW)
        expired = await db_find_session(conn, b"dead", NOW)
        await db_delete_session(conn, b"live")
        deleted = await db_find_session(conn, b"live", NOW)
    finally:
        await conn.close()

    assert found is not None
    assert (found.subject_kind, found.subject) == ("local_admin", "admin")
    assert found.expires_at == NOW + timedelta(hours=1)
    assert expired is None
    assert deleted is None


async def test_sessions_unknown_subject_kind_rejected_by_base(blank_db: str) -> None:
    conn = await _migrated(blank_db)
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await db_create_session(conn, b"x", "oidc", "sub", NOW + timedelta(hours=1))
    finally:
        await conn.close()
