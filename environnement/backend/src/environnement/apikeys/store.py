"""Les requêtes de la table des clés : lire, écrire, verrouiller.

Rien ne décide ici. Ce qu'une clé ouvre se juge contre la version servie, qui est dans
git — donc dans le service, pas dans une requête.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

import asyncpg
from miles_socle.apikeys.model import LAST_USED_GRANULARITY
from miles_socle.events.model import EventAuthor

if TYPE_CHECKING:
    # Pour le typage seul : la classe des stubs ne s'indice pas à l'exécution.
    from asyncpg.pool import PoolConnectionProxy

    Conn = PoolConnectionProxy[asyncpg.Record]

_SELECT = (
    "SELECT k.id, k.label, k.prefix, k.digest, k.created_at, k.created_by_directory,"
    " k.created_by_subject, k.revoked_at, k.last_used_at,"
    " COALESCE(array_agg(g.source ORDER BY g.source)"
    " FILTER (WHERE g.key_id IS NOT NULL), '{}') AS sources"
    " FROM api_keys k LEFT JOIN api_key_grants g ON g.key_id = k.id"
)


class KeyDb(Protocol):
    """Ce que ce module demande à une connexion : de quoi doubler sans monter une base."""

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]: ...
    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None: ...
    async def fetchval(self, query: str, *args: object) -> object: ...
    async def execute(self, query: str, *args: object) -> str: ...


@dataclass(frozen=True)
class StoredKey:
    """Une clé telle que la base la porte. Les octrois sont des NOMS, pas des objets.

    L'empreinte en fait partie : c'est elle que la vérification recompare en temps
    constant. Elle ne sort jamais de ce service — ni dans une réponse, ni dans un journal.
    """

    id: str
    label: str
    prefix: str
    digest: bytes
    sources: tuple[str, ...]
    created_at: datetime
    created_by_directory: str
    created_by_subject: str
    revoked_at: datetime | None
    last_used_at: datetime | None


def _stored(row: asyncpg.Record) -> StoredKey:
    return StoredKey(
        id=row["id"],
        label=row["label"],
        prefix=row["prefix"],
        digest=bytes(row["digest"]),
        sources=tuple(row["sources"]),
        created_at=row["created_at"],
        created_by_directory=row["created_by_directory"],
        created_by_subject=row["created_by_subject"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
    )


async def db_insert_key(
    conn: KeyDb,
    *,
    key_id: str,
    label: str,
    prefix: str,
    digest: bytes,
    now: datetime,
    author: EventAuthor,
) -> None:
    await conn.execute(
        "INSERT INTO api_keys (id, label, prefix, digest, created_at,"
        " created_by_directory, created_by_subject) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        key_id,
        label,
        prefix,
        digest,
        now,
        author.directory,
        author.subject,
    )


async def db_write_grants(conn: KeyDb, key_id: str, sources: tuple[str, ...]) -> None:
    for source in sorted(set(sources)):
        await conn.execute(
            "INSERT INTO api_key_grants (key_id, source) VALUES ($1, $2)", key_id, source
        )


async def db_clear_grants(conn: KeyDb, key_id: str) -> None:
    await conn.execute("DELETE FROM api_key_grants WHERE key_id = $1", key_id)


async def db_key(conn: KeyDb, key_id: str) -> StoredKey | None:
    row = await conn.fetchrow(f"{_SELECT} WHERE k.id = $1 GROUP BY k.id", key_id)
    return None if row is None else _stored(row)


async def db_lock_key(conn: KeyDb, key_id: str) -> bool:
    """Verrou de ligne : deux gestes concurrents sur la même clé se suivent.

    Sans lui, un remplacement d'octrois et une révocation s'entremêlent, et la clé finit
    révoquée avec les octrois de l'autre geste — ou l'inverse.
    """
    verrouillee = await conn.fetchval("SELECT id FROM api_keys WHERE id = $1 FOR UPDATE", key_id)
    return verrouillee is not None


async def db_keys(conn: KeyDb) -> list[StoredKey]:
    rows = await conn.fetch(f"{_SELECT} GROUP BY k.id ORDER BY k.created_at, k.id")
    return [_stored(row) for row in rows]


async def db_revoke(conn: KeyDb, key_id: str, now: datetime) -> None:
    await conn.execute("UPDATE api_keys SET revoked_at = $2 WHERE id = $1", key_id, now)


async def db_key_by_digest(conn: KeyDb, digest: bytes) -> StoredKey | None:
    """La clé non révoquée portant cette empreinte, s'il y en a une.

    La révocation est dans la clause, pas dans une comparaison faite après : une clé
    révoquée ne doit pas même être chargée, et son `last_used_at` ne doit pas avancer.
    """
    row = await conn.fetchrow(
        f"{_SELECT} WHERE k.digest = $1 AND k.revoked_at IS NULL GROUP BY k.id", digest
    )
    return None if row is None else _stored(row)


async def db_touch(conn: KeyDb, key_id: str, now: datetime) -> None:
    """Avance la date de dernier usage, au plus une fois par fenêtre.

    L'écrire à chaque appel ferait une écriture en base par dépôt, pour une information
    qui ne sert qu'à l'inventaire — « cette clé sert-elle encore ? ».
    """
    await conn.execute(
        "UPDATE api_keys SET last_used_at = $2 WHERE id = $1"
        " AND (last_used_at IS NULL OR last_used_at <= $3)",
        key_id,
        now,
        now - LAST_USED_GRANULARITY,
    )
