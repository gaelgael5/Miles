"""Écrire dans le journal d'events, un event ou N, dans la transaction de la modification.

**L'écriture est ENSEMBLIÈRE depuis le 06/11/2026** (Gael : « il faut que ce soit rapide
et optimisé »). `db_write_events` écrit N events en **trois instructions, quel que soit
N** ; `db_write_event` n'est plus qu'un lot d'un seul, pour que les cent quatre appels
unitaires du dépôt passent par le chemin qu'un import de masse éprouve — une seconde
implémentation aurait fini par écrire deux journaux différents.

Ce qui l'a motivé : un import écrit un event par objet (décision du 03/11/2026), et trois
allers-retours par event faisaient cent cinquante mille instructions pour cinquante mille
objets, dans la transaction que le critère 9 veut COURTE.

La relecture de l'histoire d'un objet est dans `history.py`.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import asyncpg
import structlog

from miles_socle.events.model import (
    DelegatedAuthor,
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


# Une seule instruction réserve les numéros de TOUS les objets du lot.
#
# `count(*)` et non `1` : un objet visé par plusieurs events du même lot avance d'autant,
# et c'est ce qui permet d'écrire un lot sans le découper. Le numéro RENDU est le DERNIER
# attribué ; l'appelant en déduit les précédents, qui sont contigus par construction.
# Regrouper est d'ailleurs obligatoire et pas seulement économe : deux lignes de même clé
# dans un `ON CONFLICT DO UPDATE` font échouer l'instruction entière (« cannot affect row
# a second time »), donc un lot qui touche deux fois le même objet ne passerait pas.
#
# Les objets sont verrouillés dans un ordre fixe (tri par type puis identifiant) : deux
# events de masse qui se recouvrent prennent alors leurs verrous dans le même ordre et ne
# peuvent pas s'interbloquer. L'ordre est désormais imposé PAR L'INSTRUCTION et non par le
# tri que l'appelant aurait fait — un appelant qui l'oublierait rouvrait l'interblocage.
_NEXT_SEQUENCES = """
INSERT INTO event_object_sequences (object_kind, object_id, last_sequence)
SELECT kind, id, occurrences FROM (
    SELECT kind, id, count(*)::bigint AS occurrences
    FROM unnest($1::text[], $2::text[]) AS t(kind, id)
    GROUP BY kind, id
) g
ORDER BY kind, id
ON CONFLICT (object_kind, object_id)
DO UPDATE SET last_sequence = event_object_sequences.last_sequence + excluded.last_sequence
RETURNING object_kind, object_id, last_sequence
"""

# `properties` arrive en `text[]` puis est converti dans le SELECT : annoncer `jsonb[]`
# ferait dépendre l'encodage d'une inférence du pilote, qui peut changer sous nous.
_INSERT_EVENTS = """
INSERT INTO events (id, type, functional_at, functional_at_source, written_at,
                    author_directory, author_subject, properties)
SELECT id, type, functional_at, source, $8, directory, subject, properties::jsonb
FROM unnest($1::uuid[], $2::text[], $3::timestamptz[], $4::text[],
            $5::text[], $6::text[], $7::text[])
     AS t(id, type, functional_at, source, directory, subject, properties)
"""

# `written_at` recopié depuis l'event, et non joint : c'est la clé de partition, et les
# deux tables doivent porter les mêmes bornes pour que la purge emporte un event et ses
# liens dans le même geste. La clé étrangère vers `events` a été retirée pour cette raison
# (mesuré le 03/11/2026 : PostgreSQL refuse de retirer une partition dont une contrainte
# dépend) ; l'invariant « tout event_id désigne un event présent » est désormais tenu par
# cette recopie et par l'atomicité de la purge, et un test d'intégration l'éprouve.
_INSERT_EVENT_OBJECTS = """
INSERT INTO event_objects (object_kind, object_id, sequence, event_id, written_at)
SELECT kind, id, seq, event_id, $5
FROM unnest($1::text[], $2::text[], $3::bigint[], $4::uuid[]) AS t(kind, id, seq, event_id)
"""


@dataclass(frozen=True)
class _Scelle:
    """Un event du lot, et ce qui en a été dérivé avant toute écriture."""

    event: NewEvent
    event_id: uuid.UUID
    functional_at: datetime
    source: FunctionalAtSource
    properties: dict[str, Any]
    objects: tuple[ObjectRef, ...]


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
    return (await db_write_events(db, (event,), catalog, now))[0]


async def db_write_events(
    db: EventDb,
    events: Sequence[NewEvent],
    catalog: EventTypeCatalog,
    now: Callable[[], datetime],
) -> list[WrittenEvent]:
    """Écrit le lot d'events en trois instructions, dans la transaction de l'appelant.

    **Tous les events du lot portent le MÊME `written_at`**, et c'est voulu : ils sont
    écrits par la même transaction, donc observables au même instant. Un instant par event
    aurait pu les répartir sur deux partitions à la frontière d'une journée, et la seconde
    aurait manqué alors que la première venait d'être posée.

    Un lot VIDE n'écrit rien et ne refuse rien : c'est le cas normal d'un import dont
    aucun objet n'a changé, et lever ferait de « rien à tracer » une anomalie.
    """
    if not events:
        return []
    if not db.is_in_transaction():
        raise EventError("db_write_events exige la transaction de la modification")
    for event in events:
        catalog.check(event.type)
    written_at = now()
    scelles = [_scelle(event, written_at) for event in events]
    sequences = await _reserved(db, scelles)

    async def ecrire() -> None:
        await _db_insert_events(db, scelles, written_at)
        await _db_insert_links(db, scelles, sequences, written_at)

    await _write_in_partition(db, ecrire, written_at)
    return [
        WrittenEvent(
            s.event_id,
            s.event.type,
            s.functional_at,
            s.source,
            written_at,
            s.event.author,
            s.properties,
            attribues,
        )
        for s, attribues in zip(scelles, sequences, strict=True)
    ]


def _scelle(event: NewEvent, written_at: datetime) -> _Scelle:
    functional_at = event.functional_at or written_at
    source: FunctionalAtSource = "caller" if event.functional_at is not None else "write_time"
    return _Scelle(
        event=event,
        event_id=uuid.uuid4(),
        functional_at=functional_at,
        source=source,
        properties=_properties(event),
        objects=tuple(sorted(event.objects)),
    )


async def _reserved(db: EventDb, scelles: Sequence[_Scelle]) -> list[dict[ObjectRef, int]]:
    """Les numéros de séquence de chaque event, dans l'ordre du lot.

    Le dernier numéro attribué à un objet est rendu par la base ; les précédents s'en
    déduisent parce qu'ils sont CONTIGUS — c'est l'instruction qui le garantit, en
    ajoutant le nombre d'occurrences en une fois. On remonte donc au numéro d'avant le
    lot, puis on redescend event par event dans l'ordre où ils seront écrits.
    """
    plats = [ref for s in scelles for ref in s.objects]
    rendus = await db.fetch(_NEXT_SEQUENCES, [r.kind for r in plats], [r.id for r in plats])
    derniers = {
        ObjectRef(r["object_kind"], r["object_id"]): int(r["last_sequence"]) for r in rendus
    }
    occurrences = Counter(plats)
    manquants = set(occurrences) - set(derniers)
    if manquants:
        # Jamais de repli sur un numéro deviné : deux events porteraient le même, et
        # l'histoire de l'objet se lirait avec un trou ou un doublon.
        raise EventError(f"numéros de séquence non rendus pour {sorted(manquants)}")
    avant = {ref: derniers[ref] - occurrences[ref] for ref in occurrences}
    attribues: list[dict[ObjectRef, int]] = []
    for s in scelles:
        pour_cet_event: dict[ObjectRef, int] = {}
        for ref in s.objects:
            avant[ref] += 1
            pour_cet_event[ref] = avant[ref]
        attribues.append(pour_cet_event)
    return attribues


async def _db_insert_events(db: EventDb, scelles: Sequence[_Scelle], written_at: datetime) -> None:
    await db.execute(
        _INSERT_EVENTS,
        [s.event_id for s in scelles],
        [s.event.type for s in scelles],
        [s.functional_at for s in scelles],
        [s.source for s in scelles],
        [s.event.author.directory for s in scelles],
        [s.event.author.subject for s in scelles],
        [json.dumps(s.properties) for s in scelles],
        written_at,
    )


async def _db_insert_links(
    db: EventDb, scelles: Sequence[_Scelle], seqs: Sequence[dict[ObjectRef, int]], at: datetime
) -> None:
    liens = [
        (ref, attribues[ref], s.event_id)
        for s, attribues in zip(scelles, seqs, strict=True)
        for ref in s.objects
    ]
    await db.execute(
        _INSERT_EVENT_OBJECTS,
        [ref.kind for ref, _, _ in liens],
        [ref.id for ref, _, _ in liens],
        [seq for _, seq, _ in liens],
        [event_id for _, _, event_id in liens],
        at,
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
