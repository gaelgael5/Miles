"""Descendre jusqu'au tableau que le DÉCOUPAGE désigne, sans construire ce qu'on traverse.

Le découpage est un jpath streamable (`$.accounts[*]`, `$.lots[0].sites[*]`), réduit par
l'appelant à une suite de clés et d'indices. Ce module va s'y poser et rend la position du
crochet ouvrant du tableau ; il ne lit aucun item.

**Rien de ce qui précède le tableau visé n'est construit en mémoire.** Une propriété qui le
précède n'est pas forcément petite : un document dont la première clé porte cent mégaoctets
et la seconde le tableau cherché doit s'ouvrir sans que les cent mégaoctets passent en
mémoire. C'est pour ce seul usage qu'existe `skip_value`, qui traverse une valeur par
machine à états au lieu de l'analyser.

**Les deux refus sont distincts et appellent deux corrections différentes** : le découpage
ne mène à rien dans CE document (`decoupage_absent_du_document` — l'export est en cause),
ou il mène à autre chose qu'un tableau (`decoupage_ne_designe_pas_un_tableau` — le
paramétrage ou l'export). Les confondre enverrait corriger au mauvais endroit.
"""

from __future__ import annotations

from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    ITEMS_PATH_ABSENT,
    ITEMS_PATH_NOT_ARRAY,
    DocumentUnreadable,
    show,
)
from environnement.ingestion.jsonskip import skip_value
from environnement.ingestion.jsonwindow import Window, char_at, read_key, skip_blanks


def to_array(window: Window, keys: tuple[str | int, ...]) -> int:
    """La position du crochet ouvrant du tableau que `keys` désigne.

    Une suite de clés vide désigne le document lui-même : un document qui EST le tableau
    des items est une forme servie, et c'est le cas d'un export qui n'a pas d'en-tête.
    """
    position = skip_blanks(window, 0, 0)
    for rang, key in enumerate(keys):
        position = _step(window, position, key, keys[: rang + 1])
    if char_at(window, position, position) != "[":
        raise DocumentUnreadable(ITEMS_PATH_NOT_ARRAY, show(keys))
    return position


def _step(window: Window, position: int, key: str | int, atteint: tuple[str | int, ...]) -> int:
    """La position de la valeur que `key` désigne dans le conteneur ouvert à `position`."""
    ouvrant = char_at(window, position, position)
    if isinstance(key, str) and ouvrant == "{":
        return _member(window, position, key, atteint)
    if isinstance(key, int) and ouvrant == "[":
        return _element(window, position, key, atteint)
    # Le document ne porte pas, à cet endroit, le genre de conteneur que le découpage
    # suppose : un objet là où il attendait un tableau, ou un scalaire.
    raise DocumentUnreadable(ITEMS_PATH_ABSENT, show(atteint))


def _member(window: Window, position: int, key: str, atteint: tuple[str | int, ...]) -> int:
    """La position de la valeur de la propriété `key`, les autres étant traversées."""
    position += 1
    while True:
        position = skip_blanks(window, position, position, ",")
        caractere = char_at(window, position, position)
        if caractere == "}":
            # Objet parcouru en entier sans rencontrer la clé : le découpage ne désigne
            # rien dans CE document. Refus explicite, et non un tableau vide — « zéro
            # item » dirait que l'export n'avait rien à livrer, ce qui est autre chose.
            raise DocumentUnreadable(ITEMS_PATH_ABSENT, show(atteint))
        if caractere == "":
            raise DocumentUnreadable(DOCUMENT_INVALID, "objet non ferme")
        nom, position = read_key(window, position)
        position = skip_blanks(window, position, position)
        if nom == key:
            return position
        position = skip_value(window, position)


def _element(window: Window, position: int, index: int, atteint: tuple[str | int, ...]) -> int:
    """La position du `index`-ième élément, les précédents étant traversés."""
    position += 1
    rang = 0
    while True:
        position = skip_blanks(window, position, position, ",")
        caractere = char_at(window, position, position)
        if caractere == "]":
            # Indice au-delà du tableau. Refusé et non lu comme vide : un découpage qui
            # désigne `[3]` d'un tableau de deux éléments est faux, et le dire tôt évite
            # un import à zéro item qu'on prendrait pour un export vide.
            raise DocumentUnreadable(ITEMS_PATH_ABSENT, show(atteint))
        if caractere == "":
            raise DocumentUnreadable(DOCUMENT_INVALID, "tableau non ferme")
        if rang == index:
            return position
        position = skip_value(window, position)
        rang += 1
