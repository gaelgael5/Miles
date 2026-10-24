"""Lecture d'un jpath de déclaration, par le parseur du moteur (story 844f15ad).

Partagé par les sources de données et les storages : les deux déclarent des chemins que
le moteur devra évaluer. Extrait de `sources/layout.py` le jour où les storages ont eu le
même besoin — une seconde copie aurait dérivé de la première sans que rien ne le signale.
"""

from __future__ import annotations

from urban_json.ast.nodes import JsltObject, JsltPath
from urban_json.jsonpath import IndexSelector, NameSelector, PathScope

from miles.transform.engine import TemplateSyntaxError, parse_ast


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
