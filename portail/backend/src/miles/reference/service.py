from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.cultures.service import CulturesService
from miles_socle.events.model import EventAuthor, EventTypeCatalog

from miles.reference.activation import foldcase as _foldcase
from miles.reference.activation import matches
from miles.reference.activation import resolve_set_active as _resolve_set_active
from miles.reference.labels import country_name, resolve_label
from miles.reference.model import (
    Country,
)
from miles.reference.store import (
    COUNTRIES,
    db_list_countries,
)

log = structlog.get_logger(__name__)


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
        return [p for p in pays if matches(aiguille, p.slug, p.alpha2, p.label)]

    async def resolve_set_active(
        self, author: EventAuthor, slugs: Sequence[str], active: bool
    ) -> list[str]:
        """Active ou désactive une sélection. Le geste lui-même est au module partagé.

        Il l'est depuis que les fuseaux horaires en ont eu besoin — second usage, donc
        extraction : c'est la partie à invariants (verrou avant écriture, tout ou rien,
        « déjà dans l'état voulu n'est pas un changement »), et elle n'a pas à exister à
        deux endroits.
        """
        return await _resolve_set_active(
            pool=self.pool,
            catalog=self.catalog,
            now=self.now,
            referential=COUNTRIES,
            author=author,
            slugs=slugs,
            active=active,
        )


def _libelle(alpha2: str, slug: str, culture: str | None, actives: frozenset[str]) -> str:
    """Le libellé d'un pays, et son repli. Fonction nommée plutôt que lambda dans la boucle :
    une fermeture sur la variable d'itération est un piège que ruff signale à juste titre."""
    return resolve_label(
        culture=culture,
        active_cultures=actives,
        derive=lambda code: country_name(alpha2, code),
        fallback=slug,
    )
