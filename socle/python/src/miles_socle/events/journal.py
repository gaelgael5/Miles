from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import asyncpg
import structlog

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
from miles_socle.journal.partitions import create_partition

log = structlog.get_logger(__name__)

# Les deux tables du journal, partitionnées à la journée par `written_at`. Nommées ici
# parce que ce sont les tables DU SOCLE : il porte les requêtes des siennes, et chaque
# produit n'en porte que la migration.
JOURNAL_TABLES = ("event_objects", "events")


class EventDb(Protocol):
    def is_in_transaction(self) -> bool: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    # Imbriquée dans une transaction ouverte, asyncpg en fait un POINT DE SAUVEGARDE :
    # c'est ce qui permet de rattraper une partition manquante sans perdre la modification
    # que l'event trace. Sans lui, l'échec avorterait la transaction entière.
    def transaction(self) -> AbstractAsyncContextManager[Any]: ...


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

# `written_at` recopié depuis l'event, et non joint : c'est la clé de partition, et les
# deux tables doivent porter les mêmes bornes pour que la purge emporte un event et ses
# liens dans le même geste. La clé étrangère vers `events` a été retirée pour cette raison
# (mesuré le 03/11/2026 : PostgreSQL refuse de retirer une partition dont une contrainte
# dépend) ; l'invariant « tout event_id désigne un event présent » est désormais tenu par
# cette recopie et par l'atomicité de la purge, et un test d'intégration l'éprouve.
_INSERT_EVENT_OBJECTS = """
INSERT INTO event_objects (object_kind, object_id, sequence, event_id, written_at)
SELECT kind, id, seq, $4, $5
FROM unnest($1::text[], $2::text[], $3::bigint[]) AS t(kind, id, seq)
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

    async def ecrire() -> None:
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
            written_at,
        )

    await _write_in_partition(db, ecrire, written_at)
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


async def _write_in_partition(
    db: EventDb, ecrire: Callable[[], Awaitable[None]], written_at: datetime
) -> None:
    """Écrit, et si la partition du jour manque, la POSE et réessaie une seule fois.

    **Pourquoi la réparation est ici et pas dans un filet de base.** Une partition par
    défaut aurait attrapé l'insertion — et, mesuré le 03/11/2026, aurait ensuite BLOQUÉ la
    création de toutes les partitions suivantes tant qu'elle n'est pas vidangée : le filet
    casse la réparation. L'entretien périodique pose sept jours d'avance ; ceci couvre le
    cas où il n'a pas tourné depuis plus longtemps, de sorte qu'un journal mal entretenu
    grossisse au lieu de faire tomber les écritures du produit.

    Le point de sauvegarde est indispensable : sans lui, l'insertion refusée avorterait la
    transaction de la modification que l'event trace, et la modification serait perdue.

    `23514` est partagé avec les violations de CHECK ordinaires ; seule l'absence de nom de
    contrainte distingue « aucune partition pour cette ligne » d'une contrainte nommée, et
    toute autre violation est RELANCÉE sans être retentée.
    """
    try:
        async with db.transaction():
            await ecrire()
        return
    except asyncpg.CheckViolationError as erreur:
        if erreur.constraint_name is not None:
            raise
    jour = written_at.date()
    log.warning(
        "journal_partition_manquante_posee",
        jour=jour.isoformat(),
        raison="entretien_non_passe",
    )
    for table in JOURNAL_TABLES:
        await db.execute(create_partition(table, jour))
    await ecrire()


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
