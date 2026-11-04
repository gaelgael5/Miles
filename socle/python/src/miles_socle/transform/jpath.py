"""Lecture d'un jpath de déclaration, par le parseur du moteur (story 844f15ad).

Partagé par les sources de données et les storages : les deux déclarent des chemins que
le moteur devra évaluer. Extrait de `sources/layout.py` le jour où les storages ont eu le
même besoin — une seconde copie aurait dérivé de la première sans que rien ne le signale.
"""

from __future__ import annotations

from dataclasses import dataclass

from urban_json.ast.nodes import JsltObject, JsltPath
from urban_json.jsonpath import (
    IndexSelector,
    NameSelector,
    PathScope,
    WildcardSelector,
)

from miles_socle.transform.engine import TemplateSyntaxError, parse_ast


def read_path(text: str) -> JsltPath | None:
    """Le jpath global que ce texte désigne, ou None s'il n'en est pas un."""
    # Lu par le parseur du moteur, dans un template minimal : jamais par une expression
    # maison, qui finirait par accepter ce que le moteur comprend autrement.
    try:
        ast = parse_ast(f'{{ "p": {text} }}')
    except TemplateSyntaxError:
        return None
    if not isinstance(ast, JsltObject):
        return None
    values = [p.value for p in ast.properties]
    path = values[0] if len(values) == 1 else None
    if not isinstance(path, JsltPath) or path.variable is not None:
        return None
    if path.compiled.scope is not PathScope.GLOBAL:
        return None
    return path


def path_keys(text: str) -> tuple[str | int, ...] | None:
    """Un chemin depuis la racine, fait de noms et d'indices ; None sinon."""
    path = read_path(text)
    if path is None or not path.compiled.is_singular or not path.compiled.segments:
        return None
    keys: list[str | int] = []
    for segment in path.compiled.segments:
        selector = segment.selectors[0]
        if isinstance(selector, NameSelector):
            keys.append(selector.name)
        elif isinstance(selector, IndexSelector):
            keys.append(selector.index)
        else:
            return None
    return tuple(keys)


def property_keys(text: str) -> list[str] | None:
    """Les noms de propriétés d'un chemin, ou None s'il porte un indice de tableau.

    Un index n'a pas de sens pour une clé ni pour une propriété indexable : les deux se
    résolvent contre un schéma, où l'on descend par nom de propriété.
    """
    keys = path_keys(text)
    if keys is None or any(isinstance(k, int) for k in keys):
        return None
    return [str(k) for k in keys]


# Pourquoi un découpage est refusé. Deux codes distincts : le texte n'est pas un jpath, ou
# c'en est un mais il demanderait de revenir en arrière. Les deux appellent une correction
# différente dans la déclaration.
SPLIT_UNREADABLE = "jpath_illisible"
SPLIT_NON_STREAMABLE = "non_streamable"


@dataclass(frozen=True)
class StreamSplit:
    """Où sont les items dans un document lu en flux : les clés du TABLEAU qui les porte.

    Les clés ne décrivent que le chemin jusqu'au tableau ; le joker final, qui désigne ses
    items, n'y figure pas — il n'est pas une étape de descente, il est ce qu'on émet.
    """

    keys: tuple[str | int, ...]


@dataclass(frozen=True)
class SplitRefusal:
    """Le motif, destiné à être montré : `code` est stable, `detail` nomme la construction."""

    code: str
    detail: str


def read_stream_split(text: str) -> StreamSplit | SplitRefusal:
    """Le découpage de ce texte s'il se lit en flux, ou le motif du refus.

    **La règle vit ICI et non du côté qui édite**, parce qu'elle a deux usages opposés :
    le module de paramétrage REFUSE à la saisie ce qui ne se lira pas, et le module
    d'environnement en DÉRIVE le chemin des items au moment de lire. Deux copies auraient
    divergé — l'une acceptant ce que l'autre refuse —, et la panne serait un import qui
    échoue sur une déclaration que son écran vient de déclarer bonne.

    Admis : des noms ou des indices depuis la racine, puis un seul joker final qui désigne
    les items du tableau. Refusés : un filtre (il faudrait voir l'item entier avant de le
    garder), une descente `..` (non bornée), un joker qui ne termine pas le chemin. En SAX
    on ne revient pas en arrière, et chacune de ces trois constructions l'exigerait.
    """
    path = read_path(text)
    if path is None:
        return SplitRefusal(SPLIT_UNREADABLE, text)
    segments = path.compiled.segments
    if not segments:
        return SplitRefusal(SPLIT_NON_STREAMABLE, "le chemin doit désigner un tableau")
    keys: list[str | int] = []
    for rank, segment in enumerate(segments):
        last = rank == len(segments) - 1
        if segment.is_recursive:
            return SplitRefusal(SPLIT_NON_STREAMABLE, "descente « .. » non bornée")
        selector = segment.selectors[0] if len(segment.selectors) == 1 else None
        if last and isinstance(selector, WildcardSelector):
            return StreamSplit(tuple(keys))
        if isinstance(selector, NameSelector):
            keys.append(selector.name)
        elif isinstance(selector, IndexSelector):
            keys.append(selector.index)
        else:
            reason = "un filtre exige l'item entier avant de le garder"
            if isinstance(selector, WildcardSelector):
                reason = "le joker doit terminer le chemin"
            return SplitRefusal(SPLIT_NON_STREAMABLE, reason)
    return SplitRefusal(SPLIT_NON_STREAMABLE, "le chemin doit finir par [*]")
