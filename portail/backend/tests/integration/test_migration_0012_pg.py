from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations

from miles.config import DEFAULT_MIGRATIONS_DIR

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
EXPIRY = datetime(2027, 1, 1, tzinfo=UTC)


async def _secret(conn: asyncpg.Connection, slug: str, secret_type: str) -> None:
    await conn.execute(
        "INSERT INTO secrets (slug, label, secret_type, key_version, nonce, ciphertext,"
        " created_at, updated_at) VALUES ($1, $1, $2, 1, '\\x00', '\\x00', $3, $3)",
        slug,
        secret_type,
        NOW,
    )


async def _workspace(conn: asyncpg.Connection, wid: str, repo: str, **access: object) -> None:
    await conn.execute(
        "INSERT INTO workspaces (id, name, repo_url, git_secret_slug, client_cert_pem,"
        " client_key_secret_slug, client_cert_not_after, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)",
        wid,
        f"Nom {wid}",
        repo,
        access.get("token"),
        access.get("pem"),
        access.get("key"),
        EXPIRY if access.get("pem") else None,
        NOW,
    )
    for slug, kind in ((access.get("token"), "workspace"), (access.get("key"), "workspace")):
        if slug:
            await conn.execute(
                "INSERT INTO secret_usages (secret_slug, consumer_kind, consumer_id)"
                " VALUES ($1, $2, $3)",
                slug,
                kind,
                wid,
            )


async def test_existing_workspaces_keep_their_access_through_a_connection(blank_db: str) -> None:
    migrations = file_load_migrations(DEFAULT_MIGRATIONS_DIR)
    before = [m for m in migrations if m.version < 12]
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, before)
        await _secret(conn, "jeton", "GIT_TOKEN")
        await _secret(conn, "cle", "GIT_CLIENT_KEY")
        await _workspace(conn, "retrait", "https://github.com/acme/cfg.git", token="jeton")
        await _workspace(conn, "caisse", "https://github.com/acme/caisse.git", pem="PEM", key="cle")

        # Arrêt à 0012 : 0013 retire les certificats, et a sa propre épreuve.
        applied = await resolve_apply_migrations(conn, [m for m in migrations if m.version <= 12])

        connections = await conn.fetch(
            "SELECT id, label, base_url, token_secret_slug, certificate_id FROM git_connections"
            " ORDER BY id"
        )
        certificate = await conn.fetchrow(
            "SELECT id, cert_pem, key_secret_slug, not_after FROM client_certificates"
        )
        workspaces = await conn.fetch(
            "SELECT id, repo_url, git_connection_id FROM workspaces ORDER BY id"
        )
        usages = await conn.fetch(
            "SELECT secret_slug, consumer_kind, consumer_id FROM secret_usages ORDER BY 1"
        )
    finally:
        await conn.close()

    assert applied[0] == 12
    assert [tuple(r) for r in connections] == [
        ("caisse", "Nom caisse", "https://github.com/acme", None, "caisse"),
        ("retrait", "Nom retrait", "https://github.com/acme", "jeton", None),
    ]
    assert tuple(certificate) == ("caisse", "PEM", "cle", EXPIRY)
    assert [tuple(r) for r in workspaces] == [
        ("caisse", "https://github.com/acme/caisse.git", "caisse"),
        ("retrait", "https://github.com/acme/cfg.git", "retrait"),
    ]
    # Les secrets restent tenus : ni l'un ni l'autre ne doit devenir supprimable.
    assert [tuple(r) for r in usages] == [
        ("cle", "client_certificate", "caisse"),
        ("jeton", "git_connection", "retrait"),
    ]


async def test_a_workspace_without_repository_cannot_half_declare_one(blank_db: str) -> None:
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        await conn.execute(
            "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES ('nu', 'Nu', $1, $1)",
            NOW,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE workspaces SET repo_url = 'https://github.com/a/b.git'")
    finally:
        await conn.close()
