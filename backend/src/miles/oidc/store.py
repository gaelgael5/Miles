from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import asyncpg

from miles.oidc.model import LABEL_CULTURE, Connector, ConnectorIdTakenError, ConnectorInput


class OidcDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


_SELECT = """
SELECT c.id, c.issuer, c.client_id, c.client_secret_slug, c.scopes, c.active,
       c.created_at, c.updated_at, coalesce(l.label, c.id) AS label
FROM oidc_connectors c
LEFT JOIN oidc_connector_labels l ON l.connector_id = c.id AND l.culture = $1
"""


def _connector(row: Any) -> Connector:
    return Connector(
        row["id"],
        row["issuer"],
        row["client_id"],
        row["client_secret_slug"],
        row["scopes"],
        row["active"],
        row["label"],
        row["created_at"],
        row["updated_at"],
    )


async def db_list_connectors(db: OidcDb, only_active: bool) -> list[Connector]:
    rows = await db.fetch(
        _SELECT + " WHERE ($2::boolean IS FALSE OR c.active) ORDER BY label, c.id",
        LABEL_CULTURE,
        only_active,
    )
    return [_connector(row) for row in rows]


async def db_get_connector(db: OidcDb, connector_id: str, lock: bool = False) -> Connector | None:
    row = await db.fetchrow(
        _SELECT + " WHERE c.id = $2" + (" FOR UPDATE OF c" if lock else ""),
        LABEL_CULTURE,
        connector_id,
    )
    return None if row is None else _connector(row)


async def db_insert_connector(
    db: OidcDb, connector_id: str, data: ConnectorInput, now: datetime
) -> None:
    try:
        await db.execute(
            "INSERT INTO oidc_connectors (id, issuer, client_id, client_secret_slug, scopes,"
            " active, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)",
            connector_id,
            data.issuer,
            data.client_id,
            data.client_secret_slug,
            data.scopes,
            data.active,
            now,
        )
    except asyncpg.UniqueViolationError:
        raise ConnectorIdTakenError(connector_id) from None
    await db_set_label(db, connector_id, data.label)


async def db_update_connector(
    db: OidcDb, connector_id: str, data: ConnectorInput, now: datetime
) -> None:
    await db.execute(
        "UPDATE oidc_connectors SET issuer = $2, client_id = $3, client_secret_slug = $4,"
        " scopes = $5, active = $6, updated_at = $7 WHERE id = $1",
        connector_id,
        data.issuer,
        data.client_id,
        data.client_secret_slug,
        data.scopes,
        data.active,
        now,
    )
    await db_set_label(db, connector_id, data.label)


async def db_set_label(db: OidcDb, connector_id: str, label: str) -> None:
    await db.execute(
        "INSERT INTO oidc_connector_labels (connector_id, culture, label) VALUES ($1, $2, $3)"
        " ON CONFLICT (connector_id, culture) DO UPDATE SET label = excluded.label",
        connector_id,
        LABEL_CULTURE,
        label,
    )


async def db_count_identities(db: OidcDb, connector_id: str) -> int:
    count: int = await db.fetchval(
        "SELECT count(*) FROM oidc_identities WHERE connector_id = $1", connector_id
    )
    return count


async def db_delete_connector(db: OidcDb, connector_id: str) -> None:
    await db.execute("DELETE FROM oidc_connectors WHERE id = $1", connector_id)


async def db_insert_attempt(
    db: OidcDb,
    digest: bytes,
    connector_id: str,
    nonce: str,
    code_verifier: str,
    expires_at: datetime,
    now: datetime,
) -> None:
    # Les tentatives abandonnées se purgent ici : la route de départ est publique, et
    # sans purge chacun pourrait remplir la table à volonté.
    await db.execute("DELETE FROM oidc_login_attempts WHERE expires_at <= $1", now)
    await db.execute(
        "INSERT INTO oidc_login_attempts (state_digest, connector_id, nonce, code_verifier,"
        " expires_at) VALUES ($1, $2, $3, $4, $5)",
        digest,
        connector_id,
        nonce,
        code_verifier,
        expires_at,
    )


async def db_take_attempt(db: OidcDb, digest: bytes, now: datetime) -> Any:
    """Consomme la tentative : DELETE … RETURNING, pour qu'un state ne serve qu'une fois."""
    return await db.fetchrow(
        "DELETE FROM oidc_login_attempts WHERE state_digest = $1 AND expires_at > $2"
        " RETURNING connector_id, nonce, code_verifier",
        digest,
        now,
    )


async def db_record_identity(db: OidcDb, connector_id: str, subject: str, now: datetime) -> None:
    await db.execute(
        "INSERT INTO oidc_identities (connector_id, subject, first_seen_at, last_seen_at)"
        " VALUES ($1, $2, $3, $3) ON CONFLICT (connector_id, subject)"
        " DO UPDATE SET last_seen_at = excluded.last_seen_at",
        connector_id,
        subject,
        now,
    )
