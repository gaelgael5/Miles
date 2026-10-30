from __future__ import annotations

import re
from dataclasses import dataclass

# Ce qu'un pays du référentiel EST, et les refus qu'il produit. Le mot « référentiel »
# est déjà pris trois fois dans ce produit — référentiels d'objets ingérés, référentiels de
# mapping de git, storages — et c'est pourquoi ni le module, ni les routes, ni l'écran ne
# s'appellent ainsi : ils s'appellent « pays ».

# ISO 3166-1 alpha-3, et rien d'autre. Un slug en alpha-2 glissé ici serait introuvable par
# qui écrit une procédure, et le libellé dérivé de CLDR serait celui d'un autre pays.
SLUG_RE = re.compile(r"^[A-Z]{3}$")
# Borne du nombre de slugs qu'un seul geste peut changer. Généreuse — on peut tout
# sélectionner — mais bornée : la charge vient d'un appel HTTP.
MAX_SLUGS_PER_CHANGE = 500
CULTURE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

COUNTRY_OBJECT_KIND = "country"
COUNTRY_ACTIVATED_EVENT = "country.activated"
COUNTRY_DEACTIVATED_EVENT = "country.deactivated"
EVENT_TYPES = frozenset({COUNTRY_ACTIVATED_EVENT, COUNTRY_DEACTIVATED_EVENT})


@dataclass(frozen=True)
class Country:
    """Un pays du référentiel, tel qu'on le montre : son code, son libellé, son état.

    `alpha2` sort AUSSI, et ce n'est pas un détail d'implémentation qui fuit : c'est le code
    que les systèmes tiers emploient le plus souvent, et un écran qui ne montrerait que
    l'alpha-3 obligerait à le retrouver ailleurs.
    """

    slug: str
    alpha2: str
    label: str
    active: bool


class CountryError(Exception):
    """Refus ; rien n'a été écrit."""


class UnknownCountriesError(CountryError):
    """Des slugs hors référentiel. Nommés, parce qu'ils viennent d'une saisie d'écran."""

    def __init__(self, slugs: tuple[str, ...]) -> None:
        super().__init__(f"{len(slugs)} pays inconnu(s)")
        self.slugs = slugs


class EmptyChangeError(CountryError):
    """Aucun pays désigné, ou trop. Un geste qui ne porte sur rien n'est pas un geste."""


def validate_slug(value: str) -> str:
    if not SLUG_RE.match(value):
        raise UnknownCountriesError((value,))
    return value


def validate_culture(value: str | None) -> str | None:
    """La culture demandée, validée AVANT d'aller lire CLDR avec elle.

    Elle vient d'un paramètre d'URL : non validée, elle partirait telle quelle dans
    `Locale.parse`, qui n'a pas à servir de garde d'entrée. Une forme inattendue est lue
    comme « pas de culture » plutôt que refusée — l'écran afficherait alors les libellés de
    repli, ce qui vaut mieux qu'une liste vide pour un paramètre mal formé.
    """
    if value is None or not CULTURE_RE.match(value):
        return None
    return value
