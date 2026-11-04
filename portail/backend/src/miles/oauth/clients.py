from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.oauth.model import CLIENT_ID_RE, checked_redirect_uri, new_client_id
from miles.workspaces.model import WorkspaceInputError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "oauth_client.created"
DELETED_EVENT = "oauth_client.deleted"
GRANTED_EVENT = "oauth_grant.created"
REVOKED_EVENT = "oauth_grant.revoked"
EVENT_TYPES = frozenset({CREATED_EVENT, DELETED_EVENT, GRANTED_EVENT, REVOKED_EVENT})


class ClientNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class OAuthClient:
    id: str
    label: str
    redirect_uris: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class OAuthClientsService:
    """Clients OAuth pré-enregistrés par l'administrateur (story 9f09cd8b).

    Pas d'enregistrement dynamique (Gael, 22/10/2026) : un client n'existe que parce
    qu'un administrateur l'a déclaré, avec ses adresses de retour exactes.
    """

    pool: asyncpg.Pool
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self) -> list[OAuthClient]:
        rows = await self.pool.fetch(
            "SELECT id, label, redirect_uris, created_at FROM oauth_clients ORDER BY created_at, id"
        )
        return [_client(r) for r in rows]

    async def resolve_get(self, client_id: str) -> OAuthClient | None:
        if not CLIENT_ID_RE.match(client_id):
            return None
        row = await self.pool.fetchrow(
            "SELECT id, label, redirect_uris, created_at FROM oauth_clients WHERE id = $1",
            client_id,
        )
        return None if row is None else _client(row)

    async def resolve_create(
        self, author: EventAuthor, label: str, redirect_uris: list[str]
    ) -> OAuthClient:
        label = checked_label(label)
        try:
            uris = tuple(dict.fromkeys(checked_redirect_uri(u) for u in redirect_uris))
        except ValueError:
            raise WorkspaceInputError("redirect_uris", "https_attendu") from None
        if not uris:
            raise WorkspaceInputError("redirect_uris", "vide")
        client = OAuthClient(new_client_id(), label, uris, self.now())
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO oauth_clients (id, label, redirect_uris, created_at,"
                " created_by_directory, created_by_subject) VALUES ($1, $2, $3, $4, $5, $6)",
                client.id,
                client.label,
                list(client.redirect_uris),
                client.created_at,
                author.directory,
                author.subject,
            )
            await _journal(conn, self, CREATED_EVENT, author, client.id, {"label": label})
        log.info("client_oauth_declare", client=client.id, redirect_uris=len(uris))
        return client

    async def resolve_delete(self, author: EventAuthor, client_id: str) -> None:
        """Supprime le client ; ses autorisations, codes et jetons tombent avec lui."""
        async with self.pool.acquire() as conn, conn.transaction():
            deleted = await conn.fetchval(
                "DELETE FROM oauth_clients WHERE id = $1 RETURNING id", client_id
            )
            if deleted is None:
                raise ClientNotFoundError(client_id)
            await _journal(conn, self, DELETED_EVENT, author, client_id, {})
        log.info("client_oauth_supprime", client=client_id)


async def _journal(
    conn: Any,
    service: OAuthClientsService,
    kind: str,
    author: EventAuthor,
    object_id: str,
    properties: dict[str, object],
) -> None:
    ref = ObjectRef("oauth_client", object_id)
    event = NewEvent(kind, (ref,), author, {"client_id": object_id, **properties})
    await db_write_event(conn, event, service.catalog, service.now)


def _client(row: asyncpg.Record) -> OAuthClient:
    return OAuthClient(row["id"], row["label"], tuple(row["redirect_uris"]), row["created_at"])
