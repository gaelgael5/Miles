from __future__ import annotations

from collections.abc import Callable, Container
from functools import lru_cache

import structlog
from babel import Locale, UnknownLocaleError
from miles_socle.cultures.service import FALLBACK_CULTURE

log = structlog.get_logger(__name__)

# Les libellés des référentiels DONNÉS, dérivés de CLDR au moment d'afficher (décision du
# 30/10/2026). Ils ne sont pas en base, et ce fichier est la seule raison pour laquelle
# Babel est une dépendance d'exécution.
#
# POURQUOI DÉRIVER PLUTÔT QUE CHARGER. Charger aurait voulu dire choisir POUR QUELLES
# cultures : les 249 pays pour les ~800 cultures du référentiel font deux cent mille lignes de
# SQL, et s'en tenir aux langues laisse sans libellé toute culture non prévue. Dérivé,
# activer une culture de plus donne aussitôt ses libellés — sans migration ni saisie.
#
# C'est aussi la pièce que le second référentiel donné réemploie (fuseaux horaires, story
# d4fb364a) : lui changera la fonction qui dérive, pas la règle de repli.


@lru_cache(maxsize=512)
def _locale(culture: str) -> Locale | None:
    """La locale CLDR d'un code de culture, ou rien si CLDR ne la connaît pas.

    Mise en cache parce qu'une lecture de 249 pays interrogerait sinon la même locale 249
    fois, et que chaque construction lit les données CLDR sur disque. Le cache est sûr : les
    données de CLDR ne changent pas en cours d'exécution, elles sont dans la bibliothèque.

    Rend `None` au lieu de lever : le référentiel des cultures porte des codes que CLDR ne
    couvre pas (`apc`, mesuré), et un libellé manquant est un cas NORMAL que la règle de
    repli traite. Lever ici ferait échouer la lecture de la liste entière pour une culture.
    """
    try:
        # `sep="-"` parce que nos codes sont du BCP 47 (`fr-FR`) et que Babel attend par
        # défaut la forme POSIX (`fr_FR`).
        return Locale.parse(culture, sep="-")
    except (UnknownLocaleError, ValueError, TypeError):
        return None


def country_name(alpha2: str, culture: str) -> str | None:
    """Le nom d'un pays dans une culture, d'après CLDR. `None` si CLDR ne l'a pas.

    Indexé par l'ALPHA-2, qui est la clé des territoires chez CLDR — c'est pour cela que
    l'alpha-2 voyage sur la ligne du référentiel, à côté du slug alpha-3.
    """
    locale = _locale(culture)
    return None if locale is None else locale.territories.get(alpha2)


def resolve_label(
    *,
    culture: str | None,
    active_cultures: Container[str],
    derive: Callable[[str], str | None],
    fallback: str,
) -> str:
    """Le libellé dans la culture du visiteur, avec la règle de repli de l'instance.

    Trois branches, et l'ordre n'est pas négociable :

    1. la **culture du visiteur**, si elle est ACTIVE. Une culture désactivée ne sert plus
       rien (cadrage, 15/10/2026) : la lire ici contournerait la décision de l'écran ;
    2. à défaut `en-US`, repli garanti de l'installation — la base elle-même refuse de le
       désactiver ;
    3. à défaut le **slug**, passé en `fallback`.

    JAMAIS un vide, et jamais le libellé d'une autre culture choisie au hasard : « Deutschland »
    affiché à un visiteur français laisserait croire à une donnée mal saisie, alors que rien
    n'est saisi ici. Et jamais une chaîne vide non plus — d'où le `if label`, qui écarte le
    libellé vide qu'une donnée CLDR incomplète pourrait rendre.
    """
    candidates = []
    if culture is not None and culture in active_cultures:
        candidates.append(culture)
    if FALLBACK_CULTURE not in candidates:
        candidates.append(FALLBACK_CULTURE)
    for candidate in candidates:
        label = derive(candidate)
        if label:
            return label
    # Ni la culture du visiteur ni le repli n'ont de libellé : le slug est toujours vrai.
    log.debug("libelle_absent_de_cldr", culture=culture, fallback=fallback)
    return fallback
