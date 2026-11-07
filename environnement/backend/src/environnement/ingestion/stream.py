"""Lire un document déposé EN FLUX : ses métadonnées d'abord, ses items ensuite.

**Deux passes sur le fichier, et c'est une décision du ticket** (story `0f14adbd`) : JSON ne
garantit pas que les clés précèdent le tableau, donc un en-tête placé APRÈS les items
arriverait trop tard pour une lecture qui ne revient pas en arrière. Le fichier étant déjà
sur disque, une première passe pour les métadonnées et une seconde pour les items lèvent la
contrainte sans imposer au tiers un ordre de clés qu'il ne contrôle pas forcément.

**Le document entier n'est jamais construit en mémoire.** Les deux passes travaillent sur
une fenêtre glissante (`jsonwindow`) : la passe des métadonnées omet le tableau des items,
celle des items en construit un à la fois. C'est tout l'objet du mode fichier, et c'est ce
que le critère 1 vérifie — par la mesure — sur un fichier nettement plus gros que ce qu'on
accepterait de garder.

**Les DEUX passes comptent, et c'est une mesure du 07/11/2026 qui l'a appris.** Sur un
document réel de 195,1 Mo, la passe des métadonnées coûtait 373 µs par item pour rendre un
en-tête de deux champs — elle traversait tout le document, jeton par jeton, pour sauter le
tableau. Elle est donc portée sur la même fenêtre que la passe des items, et le tableau
omis est DRAINÉ par l'analyseur plutôt que survolé (voir `_omit`).

**Tout est bloquant ici, délibérément** : ce module lit un fichier, et l'orchestration
l'appelle par `asyncio.to_thread`. Un parseur asynchrone n'aurait rien gagné — le fichier
est local, et c'est le processeur qui travaille.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    METADATA_TOO_LARGE,
    DocumentUnreadable,
)
from environnement.ingestion.jsonpath import to_array
from environnement.ingestion.jsonskip import measure_value, skip_value
from environnement.ingestion.jsonwindow import (
    WINDOW,
    Window,
    char_at,
    decode_value,
    read_key,
    skip_blanks,
)

# Marque d'omission du tableau des items dans la passe des métadonnées. Un objet dédié, et
# non `None` : `None` est une valeur JSON légitime, et les confondre ferait apparaître une
# propriété nulle là où le document n'en portait aucune.
_OMITTED = object()

# Caractères de texte autorisés par nœud de métadonnée attendu. Le budget se compte en
# NŒUDS, mais une valeur est désormais construite d'un seul appel d'analyseur : on ne peut
# plus refuser au cours de sa construction. Ce plafond, délibérément large, rend la borne
# de mémoire AVANT l'analyse ; le compte de nœuds, lui, décide ensuite et reste la règle.
# Sans lui, un en-tête d'un gigaoctet serait construit en entier pour être refusé après.
_TEXT_PER_NODE = 64


@dataclass
class _Budget:
    """Ce qu'il reste à construire, et le texte qu'on accepte d'analyser pour cela."""

    reste: int
    plafond: int


def file_read_metadata(
    path: Path, keys: tuple[str | int, ...], budget: int, window_size: int = WINDOW
) -> Any | None:
    """Le document SANS son tableau d'items, ou None s'il n'en reste rien.

    **Une troncature ne fait pas échouer cette passe.** C'est un écart assumé au fail
    closed habituel : un fichier coupé au milieu doit pouvoir livrer les items valides lus
    avant l'incident (critère 8), et c'est la passe des ITEMS qui porte le refus — elle
    seule sait combien d'items ont été lus, qui est l'information utile. Refuser ici
    rendrait le critère 8 inatteignable, puisqu'on n'arriverait jamais à la seconde passe.

    `budget` borne le nombre de nœuds construits. Le dépassement est refusé explicitement,
    jamais tronqué en silence — une métadonnée amputée se lirait comme une métadonnée
    complète, et c'est le genre de donnée sur laquelle un partenaire compte.
    """
    compte = _Budget(budget, budget * _TEXT_PER_NODE + 1024)
    try:
        with path.open("r", encoding="utf-8") as handle:
            window = Window(handle, window_size)
            lu, _ = _without(window, skip_blanks(window, 0, 0), keys, (), compte)
    except DocumentUnreadable as refus:
        if refus.code != DOCUMENT_INVALID:
            raise
        # Document tronqué ou malformé : voir la docstring, c'est la passe des items
        # qui refuse, parce qu'elle seule peut dire combien d'items ont été lus.
        return None
    if lu is _OMITTED or lu in ({}, []):
        # Rien d'autre que les items : pas de métadonnées, et on le dit par None plutôt
        # que par un objet vide, qui se lirait comme « un en-tête sans champ ».
        return None
    return lu


def file_iter_items(
    path: Path, keys: tuple[str | int, ...], window_size: int = WINDOW
) -> Iterator[Any]:
    """Les items du tableau que le découpage désigne, un par un.

    Lève `DocumentUnreadable` quand le document est invalide, quand le découpage ne
    désigne rien, ou quand il désigne autre chose qu'un tableau (critère 4). L'appelant
    compte ce qu'il a reçu avant le refus : c'est ce nombre que l'import rapporte.

    `window_size` n'est pas un réglage d'exploitation : il est là pour que les tests
    puissent prouver que le RÉSULTAT ne dépend pas de la taille de la fenêtre, ce qui est
    la seule façon d'éprouver le rechargement — un item à cheval sur deux fenêtres est le
    cas où une lecture par fenêtre se trompe en silence.
    """
    with path.open("r", encoding="utf-8") as handle:
        window = Window(handle, window_size)
        position = to_array(window, keys) + 1
        while True:
            position = _next_item(window, position)
            if position < 0:
                return
            item, position = decode_value(window, position, position)
            yield item


def _next_item(window: Window, position: int) -> int:
    """La position du prochain item, ou -1 quand le tableau est fermé."""
    position = skip_blanks(window, position, position, ",")
    caractere = char_at(window, position, position)
    if caractere == "]":
        return -1
    if caractere == "":
        # Le tableau n'est pas fermé : document tronqué. Les items déjà rendus restent
        # acquis à l'appelant, qui sait combien il en a lus (critères 7 et 8).
        raise DocumentUnreadable(DOCUMENT_INVALID, "tableau non ferme")
    return position


def _without(
    window: Window,
    position: int,
    keys: tuple[str | int, ...],
    path: tuple[str | int, ...],
    budget: _Budget,
) -> tuple[Any, int]:
    """La valeur à `position`, en OMETTANT le tableau que `keys` désigne, et sa fin.

    Le tableau n'est pas construit : on le traverse. L'omettre plutôt que le rendre vide
    distingue « il y avait des items » de « le document portait un tableau vide ici ».
    """
    if path == keys:
        return _OMITTED, _omit(window, position)
    if keys[: len(path)] != path:
        # Ni le tableau visé, ni sur son chemin : rien ne sera omis là-dedans, donc un
        # SEUL appel d'analyseur suffit. La parcourir clé par clé ne servirait qu'à payer
        # une traversée de frontière par nœud, ce que cette réécriture supprime.
        return _leaf(window, position, budget)
    caractere = char_at(window, position, position)
    if caractere == "{":
        return _map_without(window, position, keys, path, budget)
    if caractere == "[":
        return _list_without(window, position, keys, path, budget)
    # Sur le chemin, mais ce n'est pas un conteneur : le découpage ne désigne rien dans ce
    # document. La passe des métadonnées ne refuse pas pour autant — c'est celle des items
    # qui le fait, en nommant le découpage.
    return _leaf(window, position, budget)


def _map_without(
    window: Window,
    position: int,
    keys: tuple[str | int, ...],
    path: tuple[str | int, ...],
    budget: _Budget,
) -> tuple[dict[str, Any], int]:
    bati: dict[str, Any] = {}
    position += 1
    while True:
        position = skip_blanks(window, position, position, ",")
        caractere = char_at(window, position, position)
        if caractere == "}":
            return bati, position + 1
        if caractere == "":
            raise DocumentUnreadable(DOCUMENT_INVALID, "objet non ferme")
        nom, position = read_key(window, position)
        position = skip_blanks(window, position, position)
        lu, position = _without(window, position, keys, (*path, nom), budget)
        if lu is not _OMITTED:
            bati[nom] = lu


def _list_without(
    window: Window,
    position: int,
    keys: tuple[str | int, ...],
    path: tuple[str | int, ...],
    budget: _Budget,
) -> tuple[list[Any], int]:
    bati: list[Any] = []
    position += 1
    rang = 0
    while True:
        position = skip_blanks(window, position, position, ",")
        caractere = char_at(window, position, position)
        if caractere == "]":
            return bati, position + 1
        if caractere == "":
            raise DocumentUnreadable(DOCUMENT_INVALID, "tableau non ferme")
        lu, position = _without(window, position, keys, (*path, rang), budget)
        if lu is not _OMITTED:
            bati.append(lu)
        rang += 1


def _omit(window: Window, position: int) -> int:
    """La position juste après la valeur omise, qui n'est pas construite.

    **Un tableau est DRAINÉ par l'analyseur, item par item, et non survolé.** Mesuré le
    07/11/2026 : analyser un item pour le jeter coûte 42 µs, le survoler par machine à
    états en coûte 241. Analyser pour jeter est donc moins cher que ne pas analyser —
    le survol visite chaque guillemet du document, là où l'analyseur C n'est appelé
    qu'une fois par item. Chaque item est libéré aussitôt : la mémoire reste bornée.
    """
    if char_at(window, position, position) != "[":
        return skip_value(window, position)
    position += 1
    while True:
        suivant = _next_item(window, position)
        if suivant < 0:
            return position + 1
        _, position = decode_value(window, suivant, suivant)


def _leaf(window: Window, position: int, budget: _Budget) -> tuple[Any, int]:
    """Une valeur de métadonnée, construite d'un appel, et décomptée du budget."""
    if measure_value(window, position, budget.plafond) < 0:
        # Refusé PENDANT la traversée, donc avant toute analyse : construire un en-tête
        # démesuré pour le refuser ensuite annulerait la borne de mémoire que le mode
        # fichier promet. `measure_value` garde le début de la valeur lisible, de sorte
        # que l'analyse qui suit reparte de là.
        raise DocumentUnreadable(METADATA_TOO_LARGE)
    valeur, stop = decode_value(window, position, position)
    _spend(valeur, budget)
    return valeur, stop


def _spend(valeur: Any, budget: _Budget) -> None:
    """Décompte les nœuds de `valeur`. Parcours itératif : une pile, jamais la récursion."""
    pile = [valeur]
    while pile:
        noeud = pile.pop()
        budget.reste -= 1
        if budget.reste < 0:
            raise DocumentUnreadable(METADATA_TOO_LARGE)
        if isinstance(noeud, dict):
            pile.extend(noeud.values())
        elif isinstance(noeud, list):
            pile.extend(noeud)
