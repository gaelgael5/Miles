from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog

from miles.apikeys.model import (
    KEY_ID_RE,
    KEY_RE,
    Access,
    ApiKeyInfo,
    Grant,
    KeyPrincipal,
    key_digest,
    new_key,
    same_digest,
    shown_prefix,
)
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.workspaces.model import checked_label

log = structlog.get_logger(__name__)

if TYPE_CHECKING:
    # Pour le typage seul : la classe des stubs ne s'indice pas à l'exécution.
    from asyncpg.pool import PoolConnectionProxy

    Conn = PoolConnectionProxy[asyncpg.Record]

ISSUED_EVENT = "api_key.issued"
GRANTS_EVENT = "api_key.grants_changed"
REVOKED_EVENT = "api_key.revoked"
EVENT_TYPES = frozenset({ISSUED_EVENT, GRANTS_EVENT, REVOKED_EVENT})
# Le dernier usage se tient à la minute près : l'écrire à chaque appel ferait de chaque
# lecture MCP une écriture en base, pour une information qui ne sert qu'à l'inventaire.
LAST_USED_GRANULARITY = timedelta(minutes=1)

_SELECT = (
    "SELECT k.id, k.label, k.prefix, k.created_at, k.created_by_directory,"
    " k.created_by_subject, k.revoked_at, k.last_used_at,"
    " COALESCE(json_agg(json_build_object('workspace_id', g.workspace_id, 'access', g.access)"
    " ORDER BY g.workspace_id) FILTER (WHERE g.key_id IS NOT NULL), '[]') AS grants"
    " FROM api_keys k LEFT JOIN api_key_grants g ON g.key_id = k.id"
)


class ApiKeyNotFoundError(Exception):
    pass


class ApiKeyRevokedError(Exception):
    pass


class UnknownWorkspaceError(Exception):
    def __init__(self, workspace_id: str) -> None:
        super().__init__(workspace_id)
        self.workspace_id = workspace_id


@dataclass(frozen=True)
class ApiKeysService:
    """Clés d'API de service (story 0d4e4f75) : émission, droits, révocation, authentification."""

    pool: asyncpg.Pool
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_issue(
        self, author: EventAuthor, label: str, grants: Mapping[str, Access]
    ) -> tuple[ApiKeyInfo, str]:
        """Émet une clé ; rend (clé décrite, clé en clair). La clé en clair ne se relit plus."""
        label = checked_label(label)
        raw, key_id = new_key(), uuid.uuid4().hex
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO api_keys (id, label, prefix, digest, created_at,"
                " created_by_directory, created_by_subject) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                key_id,
                label,
                shown_prefix(raw),
                key_digest(raw),
                self.now(),
                author.directory,
                author.subject,
            )
            await _db_write_grants(conn, key_id, grants)
            await self._journal(conn, ISSUED_EVENT, author, key_id, grants)
            info = await _db_get(conn, key_id)
        log.info("cle_api_emise", key=key_id, prefix=info.prefix, workspaces=len(grants))
        return info, raw

    async def resolve_list(self) -> list[ApiKeyInfo]:
        rows = await self.pool.fetch(f"{_SELECT} GROUP BY k.id ORDER BY k.created_at, k.id")
        return [_info(row) for row in rows]

    async def resolve_set_grants(
        self, author: EventAuthor, key_id: str, grants: Mapping[str, Access]
    ) -> ApiKeyInfo:
        """Remplace les droits ; la clé ne change pas. Sans droit, elle n'accède à rien."""
        async with self.pool.acquire() as conn, conn.transaction():
            current = await _db_get_for_update(conn, key_id)
            if current.revoked_at is not None:
                raise ApiKeyRevokedError(key_id)
            await conn.execute("DELETE FROM api_key_grants WHERE key_id = $1", key_id)
            await _db_write_grants(conn, key_id, grants)
            await self._journal(conn, GRANTS_EVENT, author, key_id, grants)
            info = await _db_get(conn, key_id)
        log.info("cle_api_droits_changes", key=key_id, workspaces=len(grants))
        return info

    async def resolve_revoke(self, author: EventAuthor, key_id: str) -> tuple[ApiKeyInfo, bool]:
        """Révoque ; rend (clé, déjà_révoquée). Rejouer ne change rien et ne journalise rien."""
        async with self.pool.acquire() as conn, conn.transaction():
            current = await _db_get_for_update(conn, key_id)
            if current.revoked_at is not None:
                return current, True
            await conn.execute(
                "UPDATE api_keys SET revoked_at = $2 WHERE id = $1", key_id, self.now()
            )
            await self._journal(conn, REVOKED_EVENT, author, key_id, None)
            info = await _db_get(conn, key_id)
        log.info("cle_api_revoquee", key=key_id)
        return info, False

    async def resolve_authenticate(self, raw: str) -> KeyPrincipal | None:
        """L'appelant d'une clé présentée ; None si elle n'ouvre rien, quelle qu'en soit la raison.

        Droits relus à chaque appel, jamais mis en cache : une révocation ou un retrait de
        droit vaut dès la requête suivante (critère 3).
        """
        if not KEY_RE.match(raw):
            return None
        digest = key_digest(raw)
        row = await self.pool.fetchrow(
            _SELECT.replace("SELECT ", "SELECT k.digest, ", 1)
            + " WHERE k.digest = $1 AND k.revoked_at IS NULL GROUP BY k.id",
            digest,
        )
        if row is None or not same_digest(bytes(row["digest"]), digest):
            return None
        await self._touch(row["id"])
        info = _info(row)
        return KeyPrincipal(info.id, info.label, info.grants)

    async def _touch(self, key_id: str) -> None:
        now = self.now()
        await self.pool.execute(
            "UPDATE api_keys SET last_used_at = $2 WHERE id = $1"
            " AND (last_used_at IS NULL OR last_used_at <= $3)",
            key_id,
            now,
            now - LAST_USED_GRANULARITY,
        )

    async def _journal(
        self,
        conn: Conn,
        kind: str,
        author: EventAuthor,
        key_id: str,
        grants: Mapping[str, Access] | None,
    ) -> None:
        properties: dict[str, Any] = {"key_id": key_id}
        if grants is not None:
            properties["grants"] = {ws: access.value for ws, access in sorted(grants.items())}
        event = NewEvent(kind, (ObjectRef("api_key", key_id),), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)


async def _db_write_grants(conn: Conn, key_id: str, grants: Mapping[str, Access]) -> None:
    for workspace_id, access in sorted(grants.items()):
        try:
            # Point de sauvegarde : un workspace inconnu ne doit pas laisser la
            # transaction avortée sans qu'on puisse nommer lequel.
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO api_key_grants (key_id, workspace_id, access) VALUES ($1, $2, $3)",
                    key_id,
                    workspace_id,
                    access.value,
                )
        except asyncpg.ForeignKeyViolationError:
            raise UnknownWorkspaceError(workspace_id) from None


async def _db_get(conn: Conn, key_id: str) -> ApiKeyInfo:
    row = await conn.fetchrow(f"{_SELECT} WHERE k.id = $1 GROUP BY k.id", key_id)
    if row is None:
        raise ApiKeyNotFoundError(key_id)
    return _info(row)


async def _db_get_for_update(conn: Conn, key_id: str) -> ApiKeyInfo:
    if not KEY_ID_RE.match(key_id):
        raise ApiKeyNotFoundError(key_id)
    # Verrou de ligne : deux gestes concurrents sur la même clé se suivent, ils ne
    # s'entremêlent pas (droits remplacés pendant une révocation).
    locked = await conn.fetchval("SELECT id FROM api_keys WHERE id = $1 FOR UPDATE", key_id)
    if locked is None:
        raise ApiKeyNotFoundError(key_id)
    return await _db_get(conn, key_id)


def _info(row: asyncpg.Record) -> ApiKeyInfo:
    grants = json.loads(row["grants"]) if isinstance(row["grants"], str) else row["grants"]
    return ApiKeyInfo(
        id=row["id"],
        label=row["label"],
        prefix=row["prefix"],
        grants=tuple(Grant(g["workspace_id"], Access(g["access"])) for g in grants),
        created_at=row["created_at"],
        created_by=f"{row['created_by_subject']}@{row['created_by_directory']}",
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
    )
