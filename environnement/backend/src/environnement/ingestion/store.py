"""Les requêtes de la table des dépôts. Rien ne décide ici."""

from __future__ import annotations

import json
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
