from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

import asyncpg

from miles_socle.oidc.model import LABEL_CULTURE, Connector, ConnectorIdTakenError, ConnectorInput


class OidcDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


_SELECT = """
SELECT c.id, c.issuer, c.client_id, c.client_secret_slug, c.scopes, c.active,
       c.groups_claim, c.display_name_claim, c.recognize_admin, c.manage_associations,
       c.created_at, c.updated_at, coalesce(l.label, c.id) AS label,
       (SELECT coalesce(jsonb_object_agg(a.culture, a.label), '{}'::jsonb)
        FROM oidc_connector_labels a WHERE a.connector_id = c.id) AS labels
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
        row["groups_claim"],
        row["display_name_claim"],
        row["recognize_admin"],
        row["manage_associations"],
        row["created_at"],
        row["updated_at"],
        _json(row["labels"]),
    )


def _json(value: Any) -> dict[str, str]:
    loaded = json.loads(value) if isinstance(value, str) else value
    return dict(loaded)


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
            " active, groups_claim, display_name_claim, recognize_admin, manage_associations,"
            " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)",
            connector_id,
            data.issuer,
            data.client_id,
            data.client_secret_slug,
            data.scopes,
            data.active,
            data.groups_claim,
            data.display_name_claim,
            data.recognize_admin,
            data.manage_associations,
            now,
        )
    except asyncpg.UniqueViolationError:
        raise ConnectorIdTakenError(connector_id) from None
    await db_apply_labels(db, connector_id, data.labels)


async def db_update_connector(
    db: OidcDb, connector_id: str, data: ConnectorInput, now: datetime
) -> None:
    await db.execute(
        "UPDATE oidc_connectors SET issuer = $2, client_id = $3, client_secret_slug = $4,"
        " scopes = $5, active = $6, groups_claim = $7, display_name_claim = $8,"
        " recognize_admin = $9, manage_associations = $10, updated_at = $11 WHERE id = $1",
        connector_id,
        data.issuer,
        data.client_id,
        data.client_secret_slug,
        data.scopes,
        data.active,
        data.groups_claim,
        data.display_name_claim,
        data.recognize_admin,
        data.manage_associations,
        now,
    )
    await db_apply_labels(db, connector_id, data.labels)


async def db_apply_labels(db: OidcDb, connector_id: str, labels: Mapping[str, str]) -> None:
    """Écrit les cultures saisies ; une chaîne vide retire, une culture absente reste."""
    filled = {c: v for c, v in labels.items() if v}
    cleared = [c for c, v in labels.items() if not v]
    await db.execute(
        "INSERT INTO oidc_connector_labels (connector_id, culture, label)"
        " SELECT $1, culture, label FROM unnest($2::text[], $3::text[]) AS t(culture, label)"
        " ON CONFLICT (connector_id, culture) DO UPDATE SET label = excluded.label",
        connector_id,
        list(filled),
        list(filled.values()),
    )
    await db.execute(
        "DELETE FROM oidc_connector_labels WHERE connector_id = $1 AND culture = ANY($2::text[])",
        connector_id,
        cleared,
    )


async def db_inactive_cultures(db: OidcDb, cultures: list[str]) -> list[str]:
    """Cultures saisies qui ne sont pas actives : la saisie ne propose que les actives."""
    rows = await db.fetch(
        "SELECT c FROM unnest($1::text[]) AS t(c)"
        " WHERE NOT EXISTS (SELECT 1 FROM cultures WHERE code = c AND active) ORDER BY c",
        cultures,
    )
    return [r["c"] for r in rows]


async def db_list_public_connectors(db: OidcDb, culture: str) -> list[tuple[str, str]]:
    """(id, libellé) des connecteurs actifs, dans la culture demandée si elle est active.

    Repli sur en-US pour une culture inactive, inconnue ou non renseignée : jamais un
    identifiant technique ni une chaîne vide sur l'écran de connexion.
    """
    rows = await db.fetch(
        "SELECT c.id, coalesce(v.label, f.label, c.id) AS label FROM oidc_connectors c"
        " LEFT JOIN oidc_connector_labels f ON f.connector_id = c.id AND f.culture = $1"
        " LEFT JOIN oidc_connector_labels v ON v.connector_id = c.id AND v.culture = $2"
        "   AND EXISTS (SELECT 1 FROM cultures k WHERE k.code = $2 AND k.active)"
        " WHERE c.active ORDER BY label, c.id",
        LABEL_CULTURE,
        culture,
    )
    return [(r["id"], r["label"]) for r in rows]


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
