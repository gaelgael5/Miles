"""Relire l'histoire d'un objet dans le journal.

Séparée de l'ÉCRITURE (`journal.py`) le 06/11/2026, quand l'écriture est devenue
ensembliste : les deux faisaient 330 lignes dans un dépôt qui en plafonne les fichiers à
300. Le découpage suit ce qui change pour des raisons différentes — l'écriture bouge quand
on optimise un import de masse, la lecture bouge quand un écran demande autre chose.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from miles_socle.events.journal import EventDb
from miles_socle.events.model import EventAuthor, ObjectRef, WrittenEvent


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
        # Jointure sur les DEUX colonnes : `written_at` est la clé de partition des deux
        # tables, et sans elle le planificateur parcourt toutes les partitions des events.
        " FROM event_objects o JOIN events e ON e.id = o.event_id AND e.written_at = o.written_at"
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
