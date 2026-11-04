from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import db_schema_version, resolve_apply_migrations

from miles.config import DEFAULT_MIGRATIONS_DIR

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
MIGRATIONS = file_load_migrations(DEFAULT_MIGRATIONS_DIR)


@pytest.fixture
async def at_0012(blank_db: str) -> AsyncIterator[asyncpg.Connection]:
    """Base au schéma d'avant le retrait : un PAT, une clé de certificat, un certificat."""
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, [m for m in MIGRATIONS if m.version <= 12])
        for slug, kind in (("jeton", "GIT_TOKEN"), ("cle", "GIT_CLIENT_KEY")):
            await conn.execute(
                "INSERT INTO secrets (slug, label, secret_type, key_version, nonce, ciphertext,"
                " created_at, updated_at) VALUES ($1, $1, $2, 1, '\\x00', '\\x00', $3, $3)",
                slug,
                kind,
                NOW,
            )
        await conn.execute(
            "INSERT INTO client_certificates (id, label, cert_pem, key_secret_slug, not_after,"
            " created_at, updated_at) VALUES ('machine', 'Machine', 'PEM', 'cle', $1, $1, $1)",
            NOW,
        )
        await conn.execute(
            "INSERT INTO secret_usages (secret_slug, consumer_kind, consumer_id)"
            " VALUES ('cle', 'client_certificate', 'machine'),"
            " ('jeton', 'git_connection', 'forge')"
        )
        yield conn
    finally:
        await conn.close()


async def _connection(conn: asyncpg.Connection, cid: str, token: str | None) -> None:
    await conn.execute(
        "INSERT INTO git_connections (id, label, base_url, token_secret_slug, certificate_id,"
        " created_at, updated_at) VALUES ($1, $1, 'https://github.com/acme', $2, 'machine',"
        " $3, $3)",
        cid,
        token,
        NOW,
    )


async def test_connections_keep_their_pat_and_certificates_leave_with_their_keys(
    at_0012: asyncpg.Connection,
) -> None:
    await _connection(at_0012, "forge", "jeton")

    # Arrêt à 0013 : les suivantes ont leur propre épreuve.
    applied = await resolve_apply_migrations(at_0012, [m for m in MIGRATIONS if m.version <= 13])

    columns = await at_0012.fetch(
        "SELECT column_name, is_nullable FROM information_schema.columns"
        " WHERE table_name = 'git_connections'"
    )
    tables = await at_0012.fetchval("SELECT to_regclass('client_certificates')")
    secrets = await at_0012.fetch("SELECT slug FROM secrets ORDER BY slug")
    usages = await at_0012.fetch("SELECT secret_slug, consumer_kind FROM secret_usages")
    kept = await at_0012.fetchval("SELECT token_secret_slug FROM git_connections")

    assert applied == [13]
    nullable = {r["column_name"]: r["is_nullable"] for r in columns}
    assert "certificate_id" not in nullable
    assert nullable["token_secret_slug"] == "NO"
    assert tables is None
    assert [r["slug"] for r in secrets] == ["jeton"]
    assert [tuple(r) for r in usages] == [("jeton", "git_connection")]
    assert kept == "jeton"


async def test_connection_with_a_certificate_alone_stops_the_migration_naming_it(
    at_0012: asyncpg.Connection,
) -> None:
    await _connection(at_0012, "forge", "jeton")
    await _connection(at_0012, "proxy-b", None)
    await _connection(at_0012, "proxy-a", None)

    with pytest.raises(asyncpg.RaiseError, match="proxy-a, proxy-b"):
        await resolve_apply_migrations(at_0012, MIGRATIONS)

    # Rien n'est retiré : la migration et sa ligne de suivi sont dans la même transaction.
    assert await db_schema_version(at_0012) == 12
    assert await at_0012.fetchval("SELECT count(*) FROM client_certificates") == 1
    assert await at_0012.fetchval("SELECT count(*) FROM secrets") == 2
