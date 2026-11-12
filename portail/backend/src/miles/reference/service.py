from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import asyncpg
import structlog
from miles_socle.cultures.service import CulturesService
from miles_socle.events.catalog import EventCatalog
from miles_socle.events.model import EventAuthor

from miles.reference.activation import foldcase as _foldcase
from miles.reference.activation import matches
from miles.reference.activation import resolve_set_active as _resolve_set_active
from miles.reference.holidays import (
    DatesSource,
    HolidayDay,
    HolidayRule,
    days_in_window,
    page_url,
    window,
)
from miles.reference.labels import country_name, resolve_label
from miles.reference.model import (
    Country,
)
from miles.reference.store import (
    COUNTRIES,
    db_holiday_rule,
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
    catalog: EventCatalog
    now: Callable[[], datetime]
    # Le moteur de calendarium, construit une fois au démarrage. Passé au service plutôt
    # que construit dedans : un test de ce service éprouve un découpage de fenêtre, pas la
    # lecture de 111 fichiers de règles.
    dates: DatesSource

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
                row["has_holidays"],
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

    async def resolve_holidays(self, slug: str) -> Holidays | None:
        """Les règles d'un pays et les jours des 12 prochains mois. None : aucune règle.

        La fenêtre part d'AUJOURD'HUI, lu par l'horloge injectée du service et non par
        `date.today()` : un test qui dépend de l'horloge réelle échoue un jour sur cent, et
        celui-là échouerait précisément les jours intéressants — passages d'année et
        29 février.
        """
        row = await db_holiday_rule(self.pool, slug)
        if row is None:
            return None
        pays = str(row["calendarium_country"])
        source = str(row["source_url"])
        debut, fin = window(self.now().date())
        jours = days_in_window(self.dates, pays, debut, fin)
        return Holidays(HolidayRule(pays, source, page_url(source)), tuple(jours), debut, fin)


@dataclass(frozen=True)
class Holidays:
    """Ce qu'un pays a de fériés : d'où viennent ses règles, et ce qu'elles donnent."""

    rule: HolidayRule
    days: tuple[HolidayDay, ...]
    # Les bornes RENDUES, et non laissées à l'écran de les recalculer : il annonce la
    # fenêtre qu'il montre, et deux calculs de « 12 prochains mois » de part et d'autre
    # auraient fini par ne pas dire la même chose.
    start: date
    end: date


def _libelle(alpha2: str, slug: str, culture: str | None, actives: frozenset[str]) -> str:
    """Le libellé d'un pays, et son repli. Fonction nommée plutôt que lambda dans la boucle :
    une fermeture sur la variable d'itération est un piège que ruff signale à juste titre."""
    return resolve_label(
        culture=culture,
        active_cultures=actives,
        derive=lambda code: country_name(alpha2, code),
        fallback=slug,
    )
