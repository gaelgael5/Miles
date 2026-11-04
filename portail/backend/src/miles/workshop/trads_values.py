from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from miles.workshop.trads import TradsFileError

# Slug d'une clé (story 289c8d9f) : c'est ce que le paramétrage référencera. Même jeu de
# caractères que le nom d'un contexte, en plus long — une clé s'appelle volontiers
# `ecran_accueil_bouton_valider`. Pas de point : il suggérerait une hiérarchie, et
# inventer une syntaxe de référence est hors de ce ticket.
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,119}")
VALUE_MAX = 4000

# Caractères qui RÉORDONNENT le texte : une chaîne s'affiche alors autrement qu'elle n'est
# écrite, ce qui est un piège connu. Refusés, qu'ils viennent d'un collage depuis un
# traitement de texte ou d'ailleurs.
#   U+202A..U+202E : incorporations et forçages (LRE, RLE, PDF, LRO, RLO)
#   U+2066..U+2069 : isolats directionnels (LRI, RLI, FSI, PDI)
REORDERING = {chr(c) for c in [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]}
# Marques simples : elles ne font que donner une direction au caractère neutre voisin,
# sans rien retourner. Légitimes dans une traduction — un nom de marque latin au milieu
# d'une phrase arabe en a besoin. Acceptées, et l'écran les rend visibles.
MARKS = {"‎", "‏", "؜"}
_NAMES = {
    "‪": "U+202A LEFT-TO-RIGHT EMBEDDING",
    "‫": "U+202B RIGHT-TO-LEFT EMBEDDING",
    "‬": "U+202C POP DIRECTIONAL FORMATTING",
    "‭": "U+202D LEFT-TO-RIGHT OVERRIDE",
    "‮": "U+202E RIGHT-TO-LEFT OVERRIDE",
    "⁦": "U+2066 LEFT-TO-RIGHT ISOLATE",
    "⁧": "U+2067 RIGHT-TO-LEFT ISOLATE",
    "⁨": "U+2068 FIRST STRONG ISOLATE",
    "⁩": "U+2069 POP DIRECTIONAL ISOLATE",
}


class TradsInputError(Exception):
    """Base des refus de saisie ; le message ne porte jamais la valeur elle-même."""


class SlugError(TradsInputError):
    def __init__(self, slug: str) -> None:
        super().__init__("slug invalide")
        self.slug = slug


class ReorderingError(TradsInputError):
    """La valeur porte des caractères qui la feraient s'afficher autrement qu'écrite.

    On NOMME ce qui a été trouvé (critère 12) : sans cela, la personne voit sa valeur
    refusée sans rien pouvoir corriger, ces caractères étant invisibles.
    """

    def __init__(self, found: list[str]) -> None:
        super().__init__("caractères de direction refusés")
        self.found = found


class EmptyDefaultError(TradsInputError):
    """La valeur de la culture par défaut du workspace est obligatoire (critère 2 et 6)."""

    def __init__(self, culture: str) -> None:
        super().__init__("valeur obligatoire")
        self.culture = culture


@dataclass(frozen=True)
class Key:
    slug: str
    # Valeur par culture, seulement celles qui en portent une. Une culture absente n'est
    # pas traduite ; elle n'est jamais présente avec une chaîne vide.
    values: dict[str, str]


class _Dumper(yaml.SafeDumper):
    pass


def _literal_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Les multi-lignes en style littéral : c'est le diff qui y gagne.

    PyYAML retombe de lui-même sur un style quoté quand le littéral ne serait pas fidèle
    (espace en fin de ligne) — mesuré, les deux sens de l'aller-retour sont conservés.
    """
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _literal_str)


def checked_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug):
        raise SlugError(slug)
    return slug


def checked_value(value: str) -> str:
    """Refuse ce qui réordonne, garde le reste tel quel — espaces et retours compris.

    Aucune normalisation : une valeur est du texte que quelqu'un a écrit dans sa langue,
    et « nettoyer » les espaces ou la forme Unicode changerait ce qu'il a voulu écrire.
    """
    found = sorted({_NAMES[c] for c in value if c in REORDERING})
    if found:
        raise ReorderingError(found)
    if len(value) > VALUE_MAX:
        raise TradsInputError("valeur trop longue")
    return value


def values_of(path: str, content: str | None) -> dict[str, str]:
    """Les valeurs d'un fichier de culture : une mappe plate `slug: valeur`."""
    if content is None:
        return {}
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise TradsFileError(path, "yaml illisible") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TradsFileError(path, "une mappe de slug vers valeur est attendue")
    # Les valeurs sont du texte : un nombre ou un booléen non cité dans le fichier est
    # rendu tel quel plutôt que refusé, pour qu'un fichier écrit à la main se lise.
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


def values_text(values: dict[str, str]) -> str:
    """Le fichier d'une culture, trié par slug : deux écritures donnent le même texte.

    Trié par `sort_keys`, et non dans l'ordre d'arrivée : sans cela, ajouter une clé
    réécrirait le fichier entier dans le diff, et c'est la lisibilité du diff qui justifie
    ce format. Mesuré en inversant le drapeau — c'est lui, et lui seul, qui trie.
    """
    if not values:
        # Mappe vide plutôt que fichier vide : le fichier dit alors « cette culture est
        # connue du contexte et n'a aucune valeur », ce qu'un fichier absent ne dit pas.
        return "{}\n"
    return yaml.dump(
        values,
        Dumper=_Dumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=1000,
    )
