from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.cultures.service import CulturesService
from miles_socle.events.model import EventAuthor, EventTypeCatalog

from miles.reference.activation import foldcase, matches
from miles.reference.activation import resolve_set_active as _resolve_set_active
from miles.reference.labels import resolve_label, timezone_name
from miles.reference.model import Timezone, validate_country_slug
from miles.reference.store import TIMEZONES, db_list_timezones

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TimezonesService:
    """Référentiel donné des fuseaux horaires : on n'y fait qu'activer et désactiver.

    Le JUMEAU du référentiel des pays, et c'est délibéré : le geste d'activation vient du
    module partagé (`activation.py`), la règle de repli des libellés aussi (`labels.py`).
    Ce qui reste ici est ce qui n'appartient qu'aux fuseaux — leurs pays, et le fait que
    leur libellé se dérive de l'identifiant IANA plutôt que d'un code de territoire.
    """

    pool: asyncpg.Pool
    cultures: CulturesService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self,
        *,
        culture: str | None,
        only_active: bool,
        country: str | None = None,
        search: str | None = None,
    ) -> list[Timezone]:
        """Les fuseaux avec leur libellé et leurs pays.

        `country` est l'usage pour lequel le lien existe : un écran qui a déjà le pays ne
        propose alors que ses deux ou trois fuseaux, au lieu de trois cents. Il filtre sur
        TOUS les pays d'un fuseau, pas sur le premier — sans quoi filtrer sur `LUX` ne
        rendrait rien, le Luxembourg n'étant le premier pays d'aucune zone.
        """
        actives = frozenset(c.code for c in await self.cultures.resolve_list(only_active=True))
        rows = await db_list_timezones(self.pool, only_active, validate_country_slug(country))
        fuseaux = [
            Timezone(
                row["slug"],
                _libelle(row["slug"], culture, actives),
                tuple(row["countries"]),
                row["active"],
            )
            for row in rows
        ]
        if not search or not search.strip():
            return fuseaux
        aiguille = foldcase(search.strip())
        return [f for f in fuseaux if matches(aiguille, f.slug, f.label, *f.countries)]

    async def resolve_set_active(
        self, author: EventAuthor, slugs: Sequence[str], active: bool
    ) -> list[str]:
        """Active ou désactive une sélection. Le geste est celui du module partagé."""
        return await _resolve_set_active(
            pool=self.pool,
            catalog=self.catalog,
            now=self.now,
            referential=TIMEZONES,
            author=author,
            slugs=slugs,
            active=active,
        )


def _libelle(slug: str, culture: str | None, actives: frozenset[str]) -> str:
    """Le libellé d'un fuseau, et son repli. Fonction nommée plutôt que lambda dans la boucle."""
    return resolve_label(
        culture=culture,
        active_cultures=actives,
        derive=lambda code: timezone_name(slug, code),
        fallback=slug,
    )
