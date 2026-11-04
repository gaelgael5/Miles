"""Les primitives de lecture d'un document JSON en FLUX : descendre, construire, borner.

Séparées des deux passes (`stream.py`) parce qu'elles ne savent rien du découpage : elles
naviguent dans un document paresseux et en rendent une valeur. C'est ce qui les garde
éprouvables seules, et ce qui tient chacun des deux fichiers sous la limite de 300 lignes
du dépôt.

**Le document est lu en mode TRANSITOIRE** (le défaut de `json_stream`) : rien de ce qui a
été dépassé ne reste en mémoire, et c'est précisément la promesse du critère 1. La
contrepartie est qu'on ne revient pas en arrière — d'où les deux passes de `stream.py`.
"""

from __future__ import annotations

from typing import Any

import json_stream
from json_stream.base import StreamingJSONBase, StreamingJSONList, StreamingJSONObject

# Imbrication maximale admise dans un document déposé, et dans un item. Bornée, et le
# dépassement est RENDU comme un refus : `json_stream` tient des milliers de niveaux, mais
# il ne promet rien là-dessus, et un débordement de pile tomberait le service au lieu de
# faire refuser un dépôt fautif.
MAX_DEPTH = 100

# Pourquoi un document est illisible. Chacun dit à qui a déposé ce qu'il doit corriger.
DOCUMENT_INVALID = "document_json_invalide"
ITEMS_PATH_ABSENT = "decoupage_absent_du_document"
ITEMS_PATH_NOT_ARRAY = "decoupage_ne_designe_pas_un_tableau"
DOCUMENT_TOO_DEEP = "document_trop_imbrique"
METADATA_TOO_LARGE = "metadonnees_demesurees"


class DocumentUnreadable(Exception):
    """Le document déposé ne se lit pas. `code` est stable, `detail` aide à corriger.

    Levée pendant une passe, donc éventuellement après que des items ont déjà été émis :
    c'est l'appelant qui sait combien, et lui qui décide — tout ou rien si la transaction
    est unifiée, import incomplet sinon (critères 7 et 8).
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}:{detail}")
        self.code, self.detail = code, detail


def file_document(handle: Any) -> Any:
    """Le document, paresseux. Un scalaire au sommet revient tel quel, et n'est pas un
    nœud."""
    return json_stream.load(handle)


def descend(node: Any, keys: tuple[str | int, ...]) -> StreamingJSONList:
    """Le tableau que `keys` désigne, sans rien construire au passage.

    Les deux refus sont distincts et appellent deux corrections différentes : le chemin
    ne mène à rien dans CE document (`decoupage_absent_du_document`), ou il mène à autre
    chose qu'un tableau (`decoupage_ne_designe_pas_un_tableau`, critère 4). Les
    confondre enverrait corriger le paramétrage là où c'est l'export qui est en cause.
    """
    courant = node
    for rang, key in enumerate(keys):
        courant = _step(courant, key, keys[: rang + 1])
    if not isinstance(courant, StreamingJSONList):
        raise DocumentUnreadable(ITEMS_PATH_NOT_ARRAY, show(keys))
    return courant


def materialise(node: Any, depth: int, budget: list[int] | None = None) -> Any:
    """La valeur de ce nœud, construite entièrement.

    Entièrement, et c'est voulu pour un ITEM : c'est l'unité sur laquelle le template
    travaille (« on a forcément une expression jpath pour découper avant d'envoyer dans le
    template », Gael). Le borner refuserait un item légitimement gros, et l'évaluation du
    template est déjà bornée par son budget. `budget` ne sert qu'aux métadonnées, dont on
    attend un en-tête et non le volume du document.
    """
    if not isinstance(node, StreamingJSONBase):
        _spend(budget)
        return node
    _deeper(depth)
    _spend(budget)
    if isinstance(node, StreamingJSONObject):
        return {key: materialise(value, depth + 1, budget) for key, value in node.items()}
    return [materialise(value, depth + 1, budget) for value in node]


def show(keys: tuple[str | int, ...]) -> str:
    """Le découpage tel que l'auteur l'a écrit, pour que le refus le nomme (critère 4)."""
    rendu = "$"
    for key in keys:
        rendu += f"[{key}]" if isinstance(key, int) else f".{key}"
    return f"{rendu}[*]"


def _step(node: Any, key: str | int, atteint: tuple[str | int, ...]) -> Any:
    if isinstance(node, StreamingJSONObject) and isinstance(key, str):
        return _looked_up(node, key, atteint)
    if isinstance(node, StreamingJSONList) and isinstance(key, int):
        return _looked_up(node, key, atteint)
    # Le document ne porte pas, à cet endroit, le genre de conteneur que le découpage
    # suppose : un objet là où il attendait un tableau, ou un scalaire.
    raise DocumentUnreadable(ITEMS_PATH_ABSENT, show(atteint))


def _looked_up(node: Any, key: str | int, atteint: tuple[str | int, ...]) -> Any:
    try:
        return node[key]
    except (KeyError, IndexError):
        # Clé absente ou indice au-delà du tableau : le découpage ne désigne rien dans CE
        # document. Refus explicite, et non un tableau vide — « zéro item » dirait que
        # l'export n'avait rien à livrer, ce qui est une autre information.
        raise DocumentUnreadable(ITEMS_PATH_ABSENT, show(atteint)) from None


def _deeper(depth: int) -> None:
    if depth >= MAX_DEPTH:
        raise DocumentUnreadable(DOCUMENT_TOO_DEEP, str(MAX_DEPTH))


def _spend(budget: list[int] | None) -> None:
    if budget is None:
        return
    budget[0] -= 1
    if budget[0] < 0:
        raise DocumentUnreadable(METADATA_TOO_LARGE)
