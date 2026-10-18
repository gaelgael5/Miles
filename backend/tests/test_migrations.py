from __future__ import annotations

import pytest

from miles.db.migration_files import Migration, MigrationError
from miles.db.migrations import (
    MIGRATION_LOCK_KEY,
    db_applied_checksums,
    db_schema_version,
    resolve_apply_migrations,
    resolve_pending,
)
from tests.conftest import FakeConnection


async def test_db_applied_checksums_no_tracking_table_returns_empty() -> None:
    conn = FakeConnection(table_exists=False)

    assert await db_applied_checksums(conn) == {}  # type: ignore[arg-type]


async def test_db_applied_checksums_rows_returns_mapping() -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "aa"}, {"version": 2, "checksum": "bb"}])

    assert await db_applied_checksums(conn) == {1: "aa", 2: "bb"}  # type: ignore[arg-type]


async def test_db_schema_version_never_migrated_returns_none() -> None:
    conn = FakeConnection(table_exists=True, rows=[])

    assert await db_schema_version(conn) is None  # type: ignore[arg-type]


async def test_db_schema_version_returns_highest_applied() -> None:
    conn = FakeConnection(rows=[{"version": 2, "checksum": "b"}, {"version": 1, "checksum": "a"}])

    assert await db_schema_version(conn) == 2  # type: ignore[arg-type]


def test_resolve_pending_blank_base_returns_all(two_migrations: list[Migration]) -> None:
    assert resolve_pending(two_migrations, {}) == two_migrations


def test_resolve_pending_partially_applied_returns_rest(two_migrations: list[Migration]) -> None:
    applied = {1: two_migrations[0].checksum}

    assert resolve_pending(two_migrations, applied) == [two_migrations[1]]


def test_resolve_pending_fully_applied_returns_nothing(two_migrations: list[Migration]) -> None:
    applied = {m.version: m.checksum for m in two_migrations}

    assert resolve_pending(two_migrations, applied) == []


def test_resolve_pending_modified_applied_migration_raises(
    two_migrations: list[Migration],
) -> None:
    applied = {1: "empreinte-d-une-autre-version"}

    with pytest.raises(MigrationError, match="0001 modifiée"):
        resolve_pending(two_migrations, applied)


def test_resolve_pending_base_ahead_of_code_raises(two_migrations: list[Migration]) -> None:
    applied = {m.version: m.checksum for m in two_migrations} | {3: "cc"}

    with pytest.raises(MigrationError, match=r"absentes du dépôt : \[3\]"):
        resolve_pending(two_migrations, applied)


async def test_resolve_apply_migrations_blank_base_applies_all_in_order(
    two_migrations: list[Migration],
) -> None:
    conn = FakeConnection(table_exists=False)

    applied = await resolve_apply_migrations(conn, two_migrations)  # type: ignore[arg-type]

    assert applied == [1, 2]
    queries = [q for q, _ in conn.executed]
    assert queries[0] == "SELECT pg_advisory_lock($1)"
    assert queries[-1] == "SELECT pg_advisory_unlock($1)"
    inserted = [args[0] for q, args in conn.executed if q.startswith("INSERT")]
    assert inserted == [1, 2]


async def test_resolve_apply_migrations_up_to_date_applies_nothing(
    two_migrations: list[Migration],
) -> None:
    rows = [{"version": m.version, "checksum": m.checksum} for m in two_migrations]
    conn = FakeConnection(rows=rows)

    assert await resolve_apply_migrations(conn, two_migrations) == []  # type: ignore[arg-type]
    assert not any(q.startswith("INSERT") for q, _ in conn.executed)


async def test_resolve_apply_migrations_failure_releases_lock(
    two_migrations: list[Migration],
) -> None:
    conn = FakeConnection(table_exists=False)
    conn.fail_on = "CREATE TABLE alpha"

    with pytest.raises(RuntimeError):
        await resolve_apply_migrations(conn, two_migrations)  # type: ignore[arg-type]

    assert conn.executed[-1] == ("SELECT pg_advisory_unlock($1)", (MIGRATION_LOCK_KEY,))
    assert not any(q.startswith("INSERT") for q, _ in conn.executed)
