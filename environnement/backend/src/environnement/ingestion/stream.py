"""Lire un document déposé EN FLUX : ses métadonnées d'abord, ses items ensuite.

**Deux passes sur le fichier, et c'est une décision du ticket** (story `0f14adbd`) : JSON ne
garantit pas que les clés précèdent le tableau, donc un en-tête placé APRÈS les items
arriverait trop tard pour une lecture qui ne revient pas en arrière. Le fichier étant déjà
sur disque, une première passe pour les métadonnées et une seconde pour les items lèvent la
contrainte sans imposer au tiers un ordre de clés qu'il ne contrôle pas forcément.

**Le document entier n'est jamais construit en mémoire.** La passe des métadonnées SAUTE le
tableau des items ; celle des items construit un item à la fois. C'est tout l'objet du mode
fichier, et c'est ce que le critère 1 vérifie — par la mesure — sur un fichier nettement
plus gros que ce qu'on accepterait de garder.

**Tout est bloquant ici, délibérément** : ce module lit un fichier, et l'orchestration
l'appelle par `asyncio.to_thread`. Un parseur asynchrone n'aurait rien gagné — le fichier
est local, et c'est le processeur qui travaille.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from json_stream.base import StreamingJSONBase, StreamingJSONList, StreamingJSONObject

from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    DocumentUnreadable,
    descend,
    file_document,
    materialise,
)

# Marque d'omission du tableau des items dans la passe des métadonnées. Un objet dédié, et
# non `None` : `None` est une valeur JSON légitime, et les confondre ferait apparaître une
# propriété nulle là où le document n'en portait aucune.
_OMITTED = object()


def file_read_metadata(path: Path, keys: tuple[str | int, ...], budget: int) -> Any | None:
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
    reste = [budget]
    with path.open("rb") as handle:
        try:
            lu = _without(file_document(handle), (), keys, reste, 0)
        except ValueError:
            # Document tronqué ou malformé : voir la docstring, c'est la passe des items
            # qui refuse, parce qu'elle seule peut dire combien d'items ont été lus.
            return None
    if lu is _OMITTED or lu in ({}, []):
        # Rien d'autre que les items : pas de métadonnées, et on le dit par None plutôt
        # que par un objet vide, qui se lirait comme « un en-tête sans champ ».
        return None
    return lu


def file_iter_items(path: Path, keys: tuple[str | int, ...]) -> Iterator[Any]:
    """Les items du tableau que le découpage désigne, un par un.

    Lève `DocumentUnreadable` quand le document est invalide, quand le découpage ne
    désigne rien, ou quand il désigne autre chose qu'un tableau (critère 4). L'appelant
    compte ce qu'il a reçu avant le refus : c'est ce nombre que l'import rapporte.
    """
    with path.open("rb") as handle:
        try:
            for item in descend(file_document(handle), keys):
                yield materialise(item, 1)
        except ValueError as erreur:
            # Le message du parseur, borné : il porte la position de l'incident, qui est
            # ce qu'un déposant doit savoir pour corriger son export.
            raise DocumentUnreadable(DOCUMENT_INVALID, str(erreur)[:200]) from None


def _without(
    node: Any,
    path: tuple[str | int, ...],
    keys: tuple[str | int, ...],
    reste: list[int],
    depth: int,
) -> Any:
    """La valeur de ce nœud, en OMETTANT le tableau que `keys` désigne.

    Le tableau n'est pas construit : on l'IGNORE, et avancer dans le document paresseux
    le saute. L'omettre plutôt que le rendre vide distingue « il y avait des items » de
    « le document portait un tableau vide à cet endroit ».
    """
    if path == keys:
        return _OMITTED
    if not isinstance(node, StreamingJSONBase):
        return materialise(node, depth, reste)
    if isinstance(node, StreamingJSONObject):
        return _map_without(node, path, keys, reste, depth)
    return _list_without(node, path, keys, reste, depth)


def _map_without(
    node: StreamingJSONObject,
    path: tuple[str | int, ...],
    keys: tuple[str | int, ...],
    reste: list[int],
    depth: int,
) -> dict[str, Any]:
    bati: dict[str, Any] = {}
    for key, value in node.items():
        lu = _without(value, (*path, key), keys, reste, depth + 1)
        if lu is not _OMITTED:
            bati[key] = lu
    return bati


def _list_without(
    node: StreamingJSONList,
    path: tuple[str | int, ...],
    keys: tuple[str | int, ...],
    reste: list[int],
    depth: int,
) -> list[Any]:
    bati: list[Any] = []
    for rang, value in enumerate(node):
        lu = _without(value, (*path, rang), keys, reste, depth + 1)
        if lu is not _OMITTED:
            bati.append(lu)
    return bati
