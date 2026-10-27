from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.access import GitAccess
from miles.git.forge import RepositoryUrlError, parse_base_url
from miles.git.rights import SUFFIX_RE
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.model import (
    CONNECTION_CREATED,
    CONNECTION_DELETED,
    CONNECTION_UPDATED,
    TOKEN_TYPE,
    GitAccessConflictError,
    GitAccessInputError,
    GitAccessInUseError,
    GitAccessNotFoundError,
    GitConnection,
    validate_id,
    validate_label,
)
from miles.gitaccess.resolver import AccessResolver
from miles.secrets.model import Consumer, SecretError
from miles.secrets.service import resolve_attach_secret, resolve_detach_secret

log = structlog.get_logger(__name__)

_CONSUMER_KIND = "git_connection"
_SELECT = (
    "SELECT c.id, c.label, c.base_url, c.token_secret_slug, c.created_at,"
    " c.updated_at, coalesce(array_agg(w.id ORDER BY w.id) FILTER (WHERE w.id IS NOT NULL),"
    " '{}') AS workspaces FROM git_connections c"
    " LEFT JOIN workspaces w ON w.git_connection_id = c.id"
)


@dataclass(frozen=True)
class ConnectionInput:
    id: str
    label: str
    base_url: str
    # Optionnel à la saisie pour que l'absence se refuse en nommant le champ, comme
    # les autres refus ; une connexion enregistrée a toujours son PAT.
    token_secret_slug: str | None


def _connection(row: Any) -> GitConnection:
    data = dict(row)
    data["workspaces"] = tuple(data["workspaces"])
    return GitConnection(**data)


@dataclass(frozen=True)
class ConnectionsService:
    """Connexions aux forges git, déclarées à la racine (story 738f4b26).

    Une connexion porte l'adresse de la forge ou d'une organisation et son PAT ; les
    workspaces y choisissent la leur.
    """

    pool: asyncpg.Pool
    resolver: AccessResolver
    verifier: DependentsVerifier
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    extra_hosts: Sequence[str] = field(default=())

    async def resolve_list(self) -> list[GitConnection]:
        rows = await self.pool.fetch(_SELECT + " GROUP BY c.id ORDER BY c.label, c.id")
        return [_connection(r) for r in rows]

    async def resolve_get(self, connection_id: str) -> GitConnection:
        row = await self.pool.fetchrow(_SELECT + " WHERE c.id = $1 GROUP BY c.id", connection_id)
        if row is None:
            raise GitAccessNotFoundError("connexion")
        return _connection(row)

    async def resolve_create(
        self, author: EventAuthor, data: ConnectionInput
    ) -> tuple[GitConnection, bool]:
        """Déclare une connexion ; rend (connexion, déjà_là). Rejeu à l'identique : sans effet."""
        data = self._validate(data)
        existing = await self.pool.fetchrow(
            "SELECT label, base_url, token_secret_slug FROM git_connections WHERE id = $1",
            data.id,
        )
        if existing is not None:
            wanted = (data.label, data.base_url, data.token_secret_slug)
            if tuple(existing) == wanted:
                return await self.resolve_get(data.id), True
            raise GitAccessConflictError("identifiant_pris")
        # Accès vérifié à la déclaration (secret du bon type) : une connexion inutilisable
        # ne doit pas se découvrir au premier workspace.
        await self.resolver.access(data.token_secret_slug)
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO git_connections (id, label, base_url, token_secret_slug,"
                    " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $5)",
                    data.id,
                    data.label,
                    data.base_url,
                    data.token_secret_slug,
                    self.now(),
                )
                await _attach_token(conn, data.token_secret_slug, data.id)
                await self._event(conn, CONNECTION_CREATED, data.id, author, _summary(data))
        except asyncpg.UniqueViolationError:
            raise GitAccessConflictError("identifiant_pris") from None
        log.info("connexion_git_declaree", connection=data.id)
        return await self.resolve_get(data.id), False

    async def resolve_update(
        self, author: EventAuthor, data: ConnectionInput, suffix: str
    ) -> GitConnection:
        """Modifie une connexion ; adresse ou accès changés : chaque workspace est éprouvé."""
        if not SUFFIX_RE.match(suffix):
            raise GitAccessInputError("verification_suffix")
        data = self._validate(data)
        current = await self.resolve_get(data.id)
        access = await self.resolver.access(data.token_secret_slug)
        reports: list[Any] = []
        changed = (data.base_url, data.token_secret_slug) != (
            current.base_url,
            current.token_secret_slug,
        )
        if changed:

            async def access_for(_connection_id: str) -> GitAccess:
                return access

            reports = await self.verifier.resolve_verify(
                author, (data.id,), access_for, suffix, base_url=data.base_url
            )
        async with self.pool.acquire() as conn, conn.transaction():
            consumer = Consumer(_CONSUMER_KIND, data.id)
            await resolve_detach_secret(conn, current.token_secret_slug, consumer)
            await _attach_token(conn, data.token_secret_slug, data.id)
            await conn.execute(
                "UPDATE git_connections SET label = $2, base_url = $3, token_secret_slug = $4,"
                " updated_at = $5 WHERE id = $1",
                data.id,
                data.label,
                data.base_url,
                data.token_secret_slug,
                self.now(),
            )
            await self.verifier.db_store_reports(conn, reports)
            properties = _summary(data) | {"workspaces": len(reports)}
            await self._event(conn, CONNECTION_UPDATED, data.id, author, properties)
        log.info("connexion_git_modifiee", connection=data.id, workspaces=len(reports))
        return await self.resolve_get(data.id)

    async def resolve_delete(self, author: EventAuthor, connection_id: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT token_secret_slug FROM git_connections WHERE id = $1 FOR UPDATE",
                connection_id,
            )
            if row is None:
                raise GitAccessNotFoundError("connexion")
            users = await conn.fetch(
                "SELECT id FROM workspaces WHERE git_connection_id = $1 ORDER BY id",
                connection_id,
            )
            if users:
                raise GitAccessInUseError(tuple(r["id"] for r in users))
            await conn.execute("DELETE FROM git_connections WHERE id = $1", connection_id)
            consumer = Consumer(_CONSUMER_KIND, connection_id)
            await resolve_detach_secret(conn, row["token_secret_slug"], consumer)
            await self._event(conn, CONNECTION_DELETED, connection_id, author, {})
        log.info("connexion_git_supprimee", connection=connection_id)

    def _validate(self, data: ConnectionInput) -> ConnectionInput:
        try:
            base_url = parse_base_url(data.base_url, self.extra_hosts)
        except RepositoryUrlError:
            raise GitAccessInputError("base_url") from None
        return ConnectionInput(
            validate_id(data.id),
            validate_label(data.label),
            base_url,
            data.token_secret_slug or None,
        )

    async def _event(
        self,
        conn: Any,
        event_type: str,
        connection_id: str,
        author: EventAuthor,
        properties: dict[str, Any],
    ) -> None:
        event = NewEvent(
            event_type, (ObjectRef(_CONSUMER_KIND, connection_id),), author, properties
        )
        await db_write_event(conn, event, self.catalog, self.now)


def _summary(data: ConnectionInput) -> dict[str, Any]:
    # Le slug du PAT désigne, il ne révèle rien.
    return {"base_url": data.base_url, "token_secret_slug": data.token_secret_slug}


async def _attach_token(conn: Any, slug: str | None, connection_id: str) -> None:
    if not slug:
        raise GitAccessInputError("token_secret_slug")
    try:
        await resolve_attach_secret(conn, slug, TOKEN_TYPE, Consumer(_CONSUMER_KIND, connection_id))
    except SecretError:
        raise GitAccessInputError("token_secret_slug") from None
