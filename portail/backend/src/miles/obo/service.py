from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from miles.events.model import EventAuthor

ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ActorInvalidError(Exception):
    pass


class ActorTakenError(Exception):
    pass


@dataclass(frozen=True)
class Actor:
    """La personne derrière un appel MCP, retrouvée par son GUID d'acteur."""

    author: EventAuthor
    display_name: str
    email: str | None


@dataclass(frozen=True)
class ActorIdentitiesService:
    """GUID d'acteur des personnes (story 52ac5782) : la clé de lecture de l'OBO."""

    pool: asyncpg.Pool
    now: Callable[[], datetime]

    async def resolve_get(self, viewer: EventAuthor) -> str | None:
        value = await self.pool.fetchval(
            "SELECT actor FROM user_actor_identities"
            " WHERE viewer_directory = $1 AND viewer_subject = $2",
            viewer.directory,
            viewer.subject,
        )
        return str(value) if value is not None else None

    async def resolve_set(
        self, viewer: EventAuthor, actor: str, display_name: str, email: str | None
    ) -> None:
        actor = actor.strip()
        if not ACTOR_RE.match(actor):
            raise ActorInvalidError(actor)
        try:
            await self.pool.execute(
                "INSERT INTO user_actor_identities (viewer_directory, viewer_subject, actor,"
                " display_name, email, updated_at) VALUES ($1, $2, $3, $4, $5, $6)"
                " ON CONFLICT (viewer_directory, viewer_subject) DO UPDATE SET"
                " actor = EXCLUDED.actor, display_name = EXCLUDED.display_name,"
                " email = EXCLUDED.email, updated_at = EXCLUDED.updated_at",
                viewer.directory,
                viewer.subject,
                actor,
                display_name[:200] or viewer.subject,
                email,
                self.now(),
            )
        except asyncpg.UniqueViolationError:
            # L'unicité se tranche à l'écriture, pas par une lecture préalable : deux
            # personnes qui posent le même GUID en même temps ne passent pas toutes deux.
            raise ActorTakenError(actor) from None

    async def resolve_remove(self, viewer: EventAuthor) -> None:
        await self.pool.execute(
            "DELETE FROM user_actor_identities WHERE viewer_directory = $1 AND viewer_subject = $2",
            viewer.directory,
            viewer.subject,
        )

    async def resolve_find(self, actor: str) -> Actor | None:
        row = await self.pool.fetchrow(
            "SELECT viewer_directory, viewer_subject, display_name, email"
            " FROM user_actor_identities WHERE actor = $1",
            actor,
        )
        if row is None:
            return None
        author = EventAuthor(row["viewer_directory"], row["viewer_subject"])
        return Actor(author, row["display_name"], row["email"])
