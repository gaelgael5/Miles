"""La lecture du journal : le compte, la page, et les objets de la page.

Le compte et la page sont lus dans la MÊME transaction : entre deux requêtes, un event
écrit ferait annoncer « 51 events » au-dessus d'une page qui en montre 50 et d'une seconde
qui en montre deux — la pagination se recouvrirait sous les yeux du lecteur.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from miles_socle.events.search import EventFilter, Window, conditions


class SearchDb(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class FoundObject:
    kind: str
    id: str
    sequence: int


@dataclass(frozen=True)
class FoundEvent:
    id: str
    type: str
    functional_at: datetime
    functional_at_source: str
    written_at: datetime
    author_directory: str
    author_subject: str
    properties: dict[str, Any]
    objects: tuple[FoundObject, ...]
    # Qui a introduit ce type d'event. Sans défaut : la colonne est NOT NULL, les events
    # écrits avant la migration ayant été remplis avec la catégorie de leur produit — tous
    # les types déclarés à ce jour sont introduits par le back-office qui les écrit.
    category: int
    # Les champs de la racine commune que les events écrits avant le 12/11/2026 n'ont pas :
    # nuls, et la relecture ne doit pas tomber dessus.
    external_id: str | None = None
    dedup_key: str | None = None
    creation_date: datetime | None = None


@dataclass(frozen=True)
class EventPage:
    events: tuple[FoundEvent, ...]
    total: int
    page: int
    size: int


async def db_count_events(db: SearchDb, filtre: EventFilter, window: Window) -> int:
    ou, valeurs = conditions(filtre, window)
    # S608 signale l'assemblage, à juste titre : il n'existe pas de requête paramétrée pour
    # un nombre VARIABLE de clauses. Ce qui tient, et que les tests de `search.py`
    # vérifient : `conditions` n'interpole QUE des littéraux écrits dans son code et des
    # rangs de paramètre calculés ; toute valeur venue de l'appelant part en paramètre. Le
    # `noqa` porte sur l'assemblage, pas sur la provenance.
    sql = f"SELECT count(*) FROM events e WHERE {ou}"  # noqa: S608
    compte = await db.fetchval(sql, *valeurs)
    return int(compte or 0)


# `written_at DESC` puis `id` : le plus récent d'abord, et l'identifiant départage deux
# events de la même microseconde — sans lui, deux pages successives peuvent recouvrir la
# même ligne, PostgreSQL n'étant tenu à aucun ordre entre lignes égales.
_PAGE = """
SELECT e.id, e.type, e.functional_at, e.functional_at_source, e.written_at,
       e.author_directory, e.author_subject, e.properties, e.category,
       e.external_id, e.dedup_key, e.creation_date
FROM events e
WHERE {ou}
ORDER BY e.written_at DESC, e.id
LIMIT {limite} OFFSET {decalage}
"""

_OBJETS = """
SELECT o.event_id, o.object_kind, o.object_id, o.sequence
FROM event_objects o
WHERE (o.event_id, o.written_at) = ANY(
    SELECT unnest($1::uuid[]), unnest($2::timestamptz[])
)
ORDER BY o.object_kind, o.object_id
"""


async def db_search_events(
    db: SearchDb, filtre: EventFilter, window: Window, page: int, size: int
) -> EventPage:
    ou, valeurs = conditions(filtre, window)
    total = await db_count_events(db, filtre, window)
    rangs = (len(valeurs) + 1, len(valeurs) + 2)
    rows = await db.fetch(
        _PAGE.format(ou=ou, limite=f"${rangs[0]}", decalage=f"${rangs[1]}"),
        *valeurs,
        size,
        (page - 1) * size,
    )
    objets = await _db_objects(db, rows)
    return EventPage(
        tuple(_event(row, objets.get(str(row["id"]), ())) for row in rows), total, page, size
    )


async def _db_objects(db: SearchDb, rows: list[Any]) -> dict[str, tuple[FoundObject, ...]]:
    """Les liens des events de la page, en UNE requête.

    Le couple `(event_id, written_at)` et non l'identifiant seul : `written_at` est la clé
    de partition, et sans elle cette lecture parcourt toutes les partitions des liens.
    """
    if not rows:
        return {}
    liens = await db.fetch(
        _OBJETS, [row["id"] for row in rows], [row["written_at"] for row in rows]
    )
    par_event: dict[str, list[FoundObject]] = {}
    for lien in liens:
        par_event.setdefault(str(lien["event_id"]), []).append(
            FoundObject(lien["object_kind"], lien["object_id"], int(lien["sequence"]))
        )
    return {identifiant: tuple(objets) for identifiant, objets in par_event.items()}


def _event(row: Any, objets: tuple[FoundObject, ...]) -> FoundEvent:
    brut = row["properties"]
    return FoundEvent(
        str(row["id"]),
        row["type"],
        row["functional_at"],
        row["functional_at_source"],
        row["written_at"],
        row["author_directory"],
        row["author_subject"],
        json.loads(brut) if isinstance(brut, str) else brut,
        objets,
        row["category"],
        row["external_id"],
        row["dedup_key"],
        row["creation_date"],
    )
