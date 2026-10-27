from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from miles_socle.events.model import (
    DelegatedAuthor,
    EventAuthor,
    EventError,
    EventTypeCatalog,
    FunctionalAtSource,
    NewEvent,
    ObjectRef,
    WrittenEvent,
)


class EventDb(Protocol):
    def is_in_transaction(self) -> bool: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


# Les objets sont verrouillés dans un ordre fixe (tri par type puis identifiant) :
# deux events de masse qui se recouvrent prennent alors leurs verrous dans le même
# ordre et ne peuvent pas s'interbloquer.
_NEXT_SEQUENCES = """
INSERT INTO event_object_sequences (object_kind, object_id, last_sequence)
SELECT kind, id, 1 FROM unnest($1::text[], $2::text[]) WITH ORDINALITY AS t(kind, id, rank)
ORDER BY rank
ON CONFLICT (object_kind, object_id)
DO UPDATE SET last_sequence = event_object_sequences.last_sequence + 1
RETURNING object_kind, object_id, last_sequence
"""

_INSERT_EVENT = """
INSERT INTO events (id, type, functional_at, functional_at_source, written_at,
                    author_directory, author_subject, properties)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
"""

_INSERT_EVENT_OBJECTS = """
INSERT INTO event_objects (object_kind, object_id, sequence, event_id)
SELECT kind, id, seq, $4 FROM unnest($1::text[], $2::text[], $3::bigint[]) AS t(kind, id, seq)
"""


def _properties(event: NewEvent) -> dict[str, Any]:
    properties = dict(event.properties)
    if isinstance(event.author, DelegatedAuthor):
        # Ajouté ici, une fois pour tous les events : un module qui écrirait sans le dire
        # rendrait invisible la clé par laquelle une modification est passée.
        via = "via_api_key" if event.author.via_kind == "api_key" else "via_oauth_grant"
        properties[via] = event.author.via_key_id
    return properties


async def db_write_event(
    db: EventDb,
    event: NewEvent,
    catalog: EventTypeCatalog,
    now: Callable[[], datetime],
) -> WrittenEvent:
    """Écrit l'event dans la transaction ouverte par la modification qu'il trace.

    Hors transaction, refus : l'event et la modification doivent réussir ou
    échouer ensemble — aucune modification sans trace, jamais deux transactions.
    """
    if not db.is_in_transaction():
        raise EventError("db_write_event exige la transaction de la modification")
    catalog.check(event.type)
    written_at = now()
    functional_at = event.functional_at or written_at
    source: FunctionalAtSource = "caller" if event.functional_at is not None else "write_time"
    objects = sorted(event.objects)
    rows = await db.fetch(_NEXT_SEQUENCES, [o.kind for o in objects], [o.id for o in objects])
    sequences = {ObjectRef(r["object_kind"], r["object_id"]): r["last_sequence"] for r in rows}
    event_id = uuid.uuid4()
    properties = _properties(event)
    await db.execute(
        _INSERT_EVENT,
        event_id,
        event.type,
        functional_at,
        source,
        written_at,
        event.author.directory,
        event.author.subject,
        json.dumps(properties),
    )
    await db.execute(
        _INSERT_EVENT_OBJECTS,
        [o.kind for o in objects],
        [o.id for o in objects],
        [sequences[o] for o in objects],
        event_id,
    )
    return WrittenEvent(
        event_id,
        event.type,
        functional_at,
        source,
        written_at,
        event.author,
        properties,
        sequences,
    )


@dataclass(frozen=True)
class ObjectHistory:
    events: Sequence[WrittenEvent]
    # Numéros absents de la séquence : une histoire incomplète se signale, elle
    # ne s'affiche pas en silence comme si elle était entière.
    missing_sequences: Sequence[int]


async def db_object_history(db: EventDb, ref: ObjectRef) -> ObjectHistory:
    rows = await db.fetch(
        "SELECT e.id, e.type, e.functional_at, e.functional_at_source, e.written_at,"
        " e.author_directory, e.author_subject, e.properties, o.sequence"
        " FROM event_objects o JOIN events e ON e.id = o.event_id"
        " WHERE o.object_kind = $1 AND o.object_id = $2 ORDER BY o.sequence",
        ref.kind,
        ref.id,
    )
    events = [_row_to_event(row, ref) for row in rows]
    present = [row["sequence"] for row in rows]
    expected = range(1, (max(present) if present else 0) + 1)
    return ObjectHistory(events, sorted(set(expected) - set(present)))


def _row_to_event(row: Any, ref: ObjectRef) -> WrittenEvent:
    properties = row["properties"]
    return WrittenEvent(
        row["id"],
        row["type"],
        row["functional_at"],
        row["functional_at_source"],
        row["written_at"],
        EventAuthor(row["author_directory"], row["author_subject"]),
        json.loads(properties) if isinstance(properties, str) else properties,
        {ref: row["sequence"]},
    )
