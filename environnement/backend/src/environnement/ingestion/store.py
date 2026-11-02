"""Les requêtes de la table des dépôts. Rien ne décide ici."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from environnement.ingestion.model import Acknowledgement

_SELECT = "SELECT id, source, mode, object_count, received_at, state FROM ingestions"


class IngestionDb(Protocol):
    """Ce que ce module demande à une connexion : de quoi doubler sans monter une base."""

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


def _ack(row: Any, *, replayed: bool) -> Acknowledgement:
    return Acknowledgement(
        id=row["id"],
        source=row["source"],
        mode=row["mode"],
        object_count=int(row["object_count"]),
        received_at=row["received_at"],
        state=row["state"],
        replayed=replayed,
    )


async def db_record_ingestion(
    db: IngestionDb,
    *,
    ingestion_id: str,
    source: str,
    entry_model: str,
    mode: str,
    version_number: int,
    key_id: str,
    key_label: str,
    now: datetime,
    size_bytes: int,
    objects: list[dict[str, object]],
    state: str,
    idempotency_key: str | None,
) -> Acknowledgement:
    """Enregistre le lot BRUT et rend l'accusé, lu de la ligne écrite.

    Lu de la ligne, et non reconstruit depuis les arguments : un stockage normalise ce
    qu'on lui donne, et l'accusé doit dire ce qui est en base.
    """
    row = await db.fetchrow(
        "INSERT INTO ingestions (id, source, entry_model, mode, version_number, key_id,"
        " key_label, received_at, size_bytes, object_count, state, idempotency_key, raw)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)"
        " RETURNING id, source, mode, object_count, received_at, state",
        ingestion_id,
        source,
        entry_model,
        mode,
        version_number,
        key_id,
        key_label,
        now,
        size_bytes,
        len(objects),
        state,
        idempotency_key,
        json.dumps(objects),
    )
    return _ack(row, replayed=False)


async def db_ingestion_by_idempotency(
    db: IngestionDb, key_id: str, idempotency_key: str
) -> Acknowledgement | None:
    """Le dépôt déjà pris sous cette clé d'idempotence, pour CETTE clé d'API.

    La portée est la clé de l'appelant : deux partenaires peuvent employer le même
    identifiant de lot sans se marcher dessus, et aucun ne peut faire rendre à l'autre
    un accusé qu'il n'a pas obtenu.
    """
    row = await db.fetchrow(
        f"{_SELECT} WHERE key_id = $1 AND idempotency_key = $2", key_id, idempotency_key
    )
    return None if row is None else _ack(row, replayed=True)


async def db_ingestion(db: IngestionDb, ingestion_id: str) -> Acknowledgement | None:
    row = await db.fetchrow(f"{_SELECT} WHERE id = $1", ingestion_id)
    return None if row is None else _ack(row, replayed=False)


@dataclass(frozen=True)
class Call:
    """Une ligne du journal des appels : UN dépôt, jamais un objet.

    Un dépôt de masse rendrait l'écran illisible autrement — le journal d'events prend n
    lignes pour n objets écrits, celui-ci en prend une.
    """

    id: str
    source: str
    mode: str
    entry_model: str
    object_count: int
    size_bytes: int
    version_number: int
    # Le libellé et le PRÉFIXE de la clé. Jamais sa valeur : elle n'est nulle part.
    key_label: str
    key_prefix: str | None
    received_at: datetime
    state: str


@dataclass(frozen=True)
class Counts:
    """De quoi dire si le service sert : un service qui répond sans être appelé n'est
    pas un service en bonne santé."""

    total: int
    since: int
    last_at: datetime | None


async def db_recent_calls(
    db: IngestionDb, *, source: str | None, limit: int, offset: int
) -> list[Call]:
    """Les derniers appels, le plus récent d'abord. Le préfixe de la clé est JOINT.

    Jointure externe : une clé effacée de la table laisserait son dépôt sans préfixe, et
    l'appel doit rester lisible — c'est justement le cas où l'on veut savoir qui a déposé.
    """
    rows = await db.fetch(
        "SELECT i.id, i.source, i.mode, i.entry_model, i.object_count, i.size_bytes,"
        " i.version_number, i.key_label, k.prefix AS key_prefix, i.received_at, i.state"
        " FROM ingestions i LEFT JOIN api_keys k ON k.id = i.key_id"
        " WHERE ($1::text IS NULL OR i.source = $1)"
        " ORDER BY i.received_at DESC, i.id DESC LIMIT $2 OFFSET $3",
        source,
        limit,
        offset,
    )
    return [
        Call(
            id=row["id"],
            source=row["source"],
            mode=row["mode"],
            entry_model=row["entry_model"],
            object_count=int(row["object_count"]),
            size_bytes=int(row["size_bytes"]),
            version_number=int(row["version_number"]),
            key_label=row["key_label"],
            key_prefix=row["key_prefix"],
            received_at=row["received_at"],
            state=row["state"],
        )
        for row in rows
    ]


async def db_call_count(db: IngestionDb, source: str | None) -> int:
    total = await db.fetchrow(
        "SELECT count(*) AS n FROM ingestions WHERE ($1::text IS NULL OR source = $1)", source
    )
    return int(total["n"])


async def db_counts(db: IngestionDb, since: datetime) -> Counts:
    """Combien de dépôts en tout, combien depuis `since`, et quand fut le dernier."""
    row = await db.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE received_at >= $1) AS recents,"
        " max(received_at) AS dernier FROM ingestions",
        since,
    )
    return Counts(total=int(row["total"]), since=int(row["recents"]), last_at=row["dernier"])


async def db_key_counts(db: IngestionDb) -> tuple[int, int]:
    """(clés actives, clés actives jamais employées).

    Jamais employée se distingue d'employée : c'est ce qui dit qu'un partenaire n'a pas
    encore branché son intégration, plutôt que de laisser croire qu'il l'a fait.
    """
    row = await db.fetchrow(
        "SELECT count(*) AS actives, count(*) FILTER (WHERE last_used_at IS NULL) AS neuves"
        " FROM api_keys WHERE revoked_at IS NULL"
    )
    return int(row["actives"]), int(row["neuves"])
