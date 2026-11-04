"""La consultation du journal d'events : une lecture, et rien d'autre.

Aucune écriture, donc aucun event écrit par ce service — lire le journal n'est pas une
modification, et un event « journal consulté » le ferait grossir de sa propre lecture.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from miles_socle.events.search import (
    EventFilter,
    Window,
    checked_page,
    missing_in_range,
    resolve_window,
)
from miles_socle.events.store_search import EventPage, db_search_events


@dataclass(frozen=True)
class SearchResult:
    page: EventPage
    window: Window
    # Renseigné seulement quand la recherche porte sur UN objet : hors de ce cas, des
    # séquences de plusieurs objets se mêleraient et un « trou » ne voudrait rien dire.
    missing_sequences: tuple[int, ...]


@dataclass(frozen=True)
class EventsService:
    pool: asyncpg.Pool
    now: Callable[[], datetime]

    async def resolve_search(self, filtre: EventFilter, page: int, size: int) -> SearchResult:
        rang, taille = checked_page(page, size)
        fenetre = resolve_window(filtre, self.now())
        # Une seule transaction : le compte et la page doivent voir le même journal, sinon
        # l'écran annonce un total qui ne correspond pas aux lignes qu'il montre.
        async with self.pool.acquire() as cnx, cnx.transaction():
            trouve = await db_search_events(cnx, filtre, fenetre, rang, taille)
        manquantes: tuple[int, ...] = ()
        if filtre.object_kind is not None and filtre.object_id is not None:
            rangs = [
                objet.sequence
                for event in trouve.events
                for objet in event.objects
                if objet.kind == filtre.object_kind and objet.id == filtre.object_id
            ]
            manquantes = tuple(missing_in_range(rangs))
        return SearchResult(trouve, fenetre, manquantes)
