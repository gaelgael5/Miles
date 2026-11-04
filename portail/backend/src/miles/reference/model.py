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
CULTURE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

COUNTRY_OBJECT_KIND = "country"
COUNTRY_ACTIVATED_EVENT = "country.activated"
COUNTRY_DEACTIVATED_EVENT = "country.deactivated"
TIMEZONE_OBJECT_KIND = "timezone"
TIMEZONE_ACTIVATED_EVENT = "timezone.activated"
TIMEZONE_DEACTIVATED_EVENT = "timezone.deactivated"
EVENT_TYPES = frozenset(
    {
        COUNTRY_ACTIVATED_EVENT,
        COUNTRY_DEACTIVATED_EVENT,
        TIMEZONE_ACTIVATED_EVENT,
        TIMEZONE_DEACTIVATED_EVENT,
    }
)


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


@dataclass(frozen=True)
class Timezone:
    """Un fuseau du référentiel, tel qu'on le montre.

    `slug` est l'identifiant IANA, et il s'affiche TOUJOURS à côté du libellé : CLDR rend
    un nom de métazone — « heure d'Europe centrale » vaut pour Paris, Berlin et Madrid —
    donc le libellé seul ne désigne aucun fuseau.

    `countries` porte TOUS les pays du fuseau, dans l'ordre d'IANA, et il n'est JAMAIS
    vide : la table `zone1970.tab` donne au moins un pays à chacune de ses zones, et rien
    n'est ajouté à cette table. Mesuré le 30/10/2026 : 93 pays n'apparaissent jamais en
    première position, donc n'en garder qu'un les laisserait tous sans aucun fuseau.
    """

    slug: str
    label: str
    countries: tuple[str, ...]
    active: bool


def validate_country_slug(value: str | None) -> str | None:
    """Le pays sur lequel filtrer, validé AVANT d'entrer dans une requête.

    Il vient d'un paramètre d'URL. Une forme inattendue est lue comme « pas de filtre »
    plutôt que refusée : la requête est paramétrée, donc il n'y a aucun danger à la passer,
    mais un slug impossible ne rendrait rien et l'écran afficherait une liste vide sans
    dire pourquoi. Mieux vaut montrer tous les fuseaux — ce qui se voit — que rien.
    """
    if value is None or not SLUG_RE.match(value):
        return None
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
