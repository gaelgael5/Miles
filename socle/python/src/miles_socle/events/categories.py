"""La catégorie d'un type d'event : QUI l'introduit, et donc qui peut l'éditer.

Décision de Gael du 12/11/2026 : « tout event est visible fonctionnellement dans l'ihm de
configuration. si l'event est introduit par du code, dans ce cas il est en lecture seul
dans l'ihm. on introduit une notion de catégorie pour identifier qui introduit l'event. »
Puis, sur la proposition de découper les events de back-office en nommant les trois
back-offices : « Oui la liste à l'air bien. »

**Ce que la catégorie décide, et c'est son seul vrai enjeu** : le VERROU de l'IHM de
configuration. `code_introduced` n'est pas une étiquette décorative — c'est lui qui dit si
l'écran propose d'éditer le type ou le montre en lecture seule. Le dériver autrement (du
chemin du fichier, de l'absence de déclaration dans git…) donnerait un verrou qui change
quand on réorganise un répertoire.

**Les numéros sont déclarés ici** parce que Gael les a posés avec les noms (« 0 pour
system-backend, 1-system-front »), et ils sont **stables** : réordonner la liste
changerait la valeur portée par des events déjà écrits. Un nom ne porte pas ce risque,
d'où les deux côte à côte. **Ce que le contrat publié expose — le numéro ou le nom — n'est
pas encore tranché**, et c'est pour cela que ce module ne décide pas de la forme du fil :
il déclare le vocabulaire, une seule fois, et le contrat choisira.

**Ce que le contrat publie, tranché le 12/11/2026** : « On reste sur les numéros ». C'est
donc le NUMÉRO qui voyage, et la racine commune déclare `Category` en entier énuméré — le
nom reste ici, pour les écrans et pour la lecture d'un diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


class UnknownCategoryError(ValueError):
    """Catégorie inconnue : refus. Pas de repli sur une valeur plausible."""


@dataclass(frozen=True)
class EventCategory:
    """Une catégorie déclarée : son numéro stable, son nom, et ce qu'elle autorise."""

    number: int
    slug: str
    #: Vrai quand c'est du code qui introduit le type : l'IHM le montre en lecture seule.
    code_introduced: bool


CATEGORIES: Final[tuple[EventCategory, ...]] = (
    # Les trois back-offices sont nommés séparément, et non regroupés en un
    # « system-backend » : dans le journal, « lequel des trois a introduit ce type » est
    # précisément ce qu'on cherche, et un nom commun les confondrait là.
    EventCategory(0, "backoffice-configuration", code_introduced=True),
    EventCategory(1, "backoffice-enrolement", code_introduced=True),
    EventCategory(2, "backoffice-environnement", code_introduced=True),
    EventCategory(3, "system-front", code_introduced=True),
    EventCategory(4, "device-socle", code_introduced=True),
    # La seule éditable : déclarée dans le paramétrage du workspace, émise par le terminal.
    # C'est elle que l'écran des événements laisse modifier.
    EventCategory(5, "device-fonctionnel", code_introduced=False),
    # Ajoutée le 12/11/2026 sur un trou MESURÉ, pas supposé : urban-workflow injecte
    # lui-même un event technique `$_result` dans chaque workflow (« technical result of
    # execution of an order pushed by the current workflow »). Il n'est introduit ni par
    # notre code, ni par une IHM, ni par un device, ni par le paramétrage — aucune des six
    # premières ne lui allait, et sans elle un workflow réel ne se chargeait pas.
    EventCategory(6, "moteur-workflow", code_introduced=True),
)

_BY_SLUG: Final[dict[str, EventCategory]] = {item.slug: item for item in CATEGORIES}
_BY_NUMBER: Final[dict[int, EventCategory]] = {item.number: item for item in CATEGORIES}


def of_slug(slug: str) -> EventCategory:
    """La catégorie de ce nom, ou un refus qui la nomme."""
    try:
        return _BY_SLUG[slug]
    except KeyError:
        raise UnknownCategoryError(f"catégorie d'event inconnue : {slug!r}") from None


def of_number(number: int) -> EventCategory:
    """La catégorie de ce numéro, ou un refus qui le nomme."""
    try:
        return _BY_NUMBER[number]
    except KeyError:
        raise UnknownCategoryError(f"numéro de catégorie d'event inconnu : {number}") from None
