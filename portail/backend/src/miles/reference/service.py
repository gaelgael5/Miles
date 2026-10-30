from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.cultures.service import CulturesService
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.reference.labels import country_name, resolve_label
from miles.reference.model import (
    COUNTRY_ACTIVATED_EVENT,
    COUNTRY_DEACTIVATED_EVENT,
    COUNTRY_OBJECT_KIND,
    MAX_SLUGS_PER_CHANGE,
    Country,
    EmptyChangeError,
    UnknownCountriesError,
)
from miles.reference.store import (
    db_list_countries,
    db_lock_countries,
    db_set_countries_active,
)

log = structlog.get_logger(__name__)


def _foldcase(text: str) -> str:
    """Repli de casse et d'accents, pour que le filtre trouve « cote » dans « Côte »."""
    decompose = unicodedata.normalize("NFD", text)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn").casefold()


@dataclass(frozen=True)
class CountriesService:
    """Référentiel donné des pays : on n'y fait qu'activer et désactiver.

    Même dispositif que les cultures, et c'est volontaire : la liste est en base, complète,
    et le seul geste d'administration est l'activation. Ni création, ni suppression, ni
    renommage — une liste saisie à la main dérive et finit par porter des codes inventés,
    et la migration suivante écraserait ce que quelqu'un y aurait ajouté.

    Ce que ce service ajoute aux cultures : les LIBELLÉS ne sont pas en base. Ils sont
    dérivés de CLDR dans la culture du visiteur, à chaque lecture (voir `labels.py`).
    """

    pool: asyncpg.Pool
    # Les cultures ACTIVES décident de la règle de repli des libellés : une culture
    # désactivée ne sert plus rien. Le service des cultures est relu à chaque lecture pour
    # la même raison que la liste des pays — une culture activée vaut aussitôt.
    cultures: CulturesService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, *, culture: str | None, only_active: bool, search: str | None = None
    ) -> list[Country]:
        """Les pays avec leur libellé dans la culture demandée.

        `search` filtre sur le slug, l'alpha-2 et le libellé DÉRIVÉ : filtrer sur le seul
        code obligerait à connaître « DEU » pour trouver l'Allemagne.
        """
        actives = frozenset(c.code for c in await self.cultures.resolve_list(only_active=True))
        rows = await db_list_countries(self.pool, only_active)
        pays = [
            Country(
                row["slug"],
                row["alpha2"],
                _libelle(row["alpha2"], row["slug"], culture, actives),
                row["active"],
            )
            for row in rows
        ]
        if not search or not search.strip():
            return pays
        aiguille = _foldcase(search.strip())
        return [
            p
            for p in pays
            if aiguille in _foldcase(p.slug)
            or aiguille in _foldcase(p.alpha2)
            or aiguille in _foldcase(p.label)
        ]

    async def resolve_set_active(
        self, author: EventAuthor, slugs: Sequence[str], active: bool
    ) -> list[str]:
        """Applique exactement la sélection reçue ; rend les slugs réellement changés.

        Écrit dans UNE transaction, verrou d'abord : l'écran envoie une sélection entière,
        et la moitié appliquée serait un état que personne n'a demandé.
        """
        voulus = sorted(set(slugs))
        if not voulus or len(voulus) > MAX_SLUGS_PER_CHANGE:
            raise EmptyChangeError
        async with self.pool.acquire() as conn, conn.transaction():
            connus = await db_lock_countries(conn, voulus)
            inconnus = tuple(slug for slug in voulus if slug not in connus)
            if inconnus:
                # Nommés, et refusés AVANT toute écriture : un slug hors référentiel vient
                # d'une saisie, et le créer au passage ferait du référentiel donné une
                # liste ouverte.
                raise UnknownCountriesError(inconnus)
            changes = await db_set_countries_active(conn, voulus, active)
            if changes:
                event = NewEvent(
                    COUNTRY_ACTIVATED_EVENT if active else COUNTRY_DEACTIVATED_EVENT,
                    tuple(ObjectRef(COUNTRY_OBJECT_KIND, slug) for slug in changes),
                    author,
                    {"count": len(changes)},
                )
                await db_write_event(conn, event, self.catalog, self.now)
        log.info("pays_changes", active=active, count=len(changes))
        return changes


def _libelle(alpha2: str, slug: str, culture: str | None, actives: frozenset[str]) -> str:
    """Le libellé d'un pays, et son repli. Fonction nommée plutôt que lambda dans la boucle :
    une fermeture sur la variable d'itération est un piège que ruff signale à juste titre."""
    return resolve_label(
        culture=culture,
        active_cultures=actives,
        derive=lambda code: country_name(alpha2, code),
        fallback=slug,
    )
