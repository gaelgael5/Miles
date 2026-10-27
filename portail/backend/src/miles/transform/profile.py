from __future__ import annotations

from dataclasses import dataclass

from urban_json import FunctionRegistry
from urban_json.ast import JsltBase
from urban_json.ast.nodes import (
    JsltArray,
    JsltBinaryOperator,
    JsltConstant,
    JsltFunctionCall,
    JsltObject,
    JsltOperator,
    JsltPath,
    JsltProperty,
    JsltSwitch,
    JsltVariable,
)
from urban_json.ast.operation import OperationEnum
from urban_json.jsonpath import FilterBinary, FilterLiteral, FilterPath, FilterSelector
from urban_json.jsonpath.filter import FilterExpression
from urban_json.jsonpath.selectors import PathFunctionSelector

# Profil d'écriture (cadrage « Langage de mapping », ticket 68cae2ff) : le sous-ensemble
# de JSLT qu'un template peut employer. Un seul profil pour les trois usages — mappings,
# configuration de compte, imports (Gael, 22/10/2026). Le moteur n'est pas amputé : on
# vérifie l'arbre qu'il produit, pour que l'agent écrive partout de la même façon.
#
# Admis : objets, tableaux, constantes ; chemins (nom, indice, joker, tranche,
# descente) ; un filtre `?(...)` ou un `$where` à un seul prédicat clos ; `$source`
# pour itérer ; `??` ; conversions `#type` ; fonctions nommées (le catalogue dira
# lesquelles existent). Refusé : arithmétique, logique, `when`, variables, négation.
# Une transformation qui en a besoin passe par une fonction nommée du catalogue.
COMPARISONS = frozenset(
    {
        OperationEnum.EQUAL,
        OperationEnum.NOT_EQUAL,
        OperationEnum.LESS_THAN,
        OperationEnum.LESS_THAN_OR_EQUAL,
        OperationEnum.GREATER_THAN,
        OperationEnum.GREATER_THAN_OR_EQUAL,
    }
)
FILTER_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">=", "in"})


@dataclass(frozen=True)
class Violation:
    """Une construction hors profil : nommée et située, pour que l'auteur la corrige."""

    construct: str
    detail: str | None
    line: int | None
    column: int | None


def check_profile(ast: JsltBase) -> tuple[Violation, ...]:
    """Toutes les constructions hors profil du template, pas seulement la première."""
    found: list[Violation] = []
    _walk(ast, found)
    return tuple(found)


def _at(node: JsltBase, construct: str, detail: str | None = None) -> Violation:
    location = node.location
    line = location.line if location is not None else None
    column = location.column if location is not None else None
    return Violation(construct, detail, line, column)


def _walk(node: JsltBase, found: list[Violation]) -> None:
    # Ordre voulu : JsltVariable avant JsltProperty, dont elle hérite.
    if isinstance(node, JsltVariable):
        found.append(_at(node, "variable", node.name))
    elif isinstance(node, JsltObject):
        _object(node, found)
    elif isinstance(node, JsltProperty):
        if node.value is not None:
            _walk(node.value, found)
    elif isinstance(node, JsltArray):
        for item in node.items:
            _walk(item, found)
    elif isinstance(node, JsltConstant):
        return
    elif isinstance(node, JsltPath):
        _path(node, found)
    elif isinstance(node, JsltFunctionCall):
        for argument in node.arguments:
            _walk(argument, found)
    elif isinstance(node, JsltBinaryOperator):
        _operator(node, found)
    elif isinstance(node, JsltOperator):
        found.append(_at(node, "operateur", node.operator.name.lower()))
    elif isinstance(node, JsltSwitch):
        found.append(_at(node, "when"))
    else:
        # Fermé par défaut : un nœud qu'une version future du moteur ajouterait n'entre
        # pas dans le profil sans qu'on l'y ait admis.
        found.append(_at(node, "construction_inconnue", type(node).__name__))


def _object(node: JsltObject, found: list[Violation]) -> None:
    for variable in node.variables:
        found.append(_at(variable, "variable", variable.name))
    if node.source is not None:
        _walk(node.source, found)
    if node.where is not None:
        _predicate(node.where, found)
    for item in node.properties:
        _walk(item, found)


def _operator(node: JsltBinaryOperator, found: list[Violation]) -> None:
    if node.operator is OperationEnum.COALESCE:
        _walk(node.left, found)
        _walk(node.right, found)
        return
    # Une comparaison n'est admise que comme prédicat d'un `$where` (voir _predicate).
    found.append(_at(node, "operateur", node.operator.name.lower()))


def _predicate(node: JsltBase, found: list[Violation]) -> None:
    """`$where` : une comparaison entre un chemin et une constante, rien d'autre."""
    if not isinstance(node, JsltBinaryOperator) or node.operator not in COMPARISONS:
        found.append(_at(node, "predicat", "une seule comparaison attendue"))
        return
    for side in (node.left, node.right):
        if not isinstance(side, (JsltPath, JsltConstant)):
            found.append(_at(side, "predicat_non_clos", "chemin ou constante attendu"))
        elif isinstance(side, JsltPath):
            _path(side, found)


def _path(node: JsltPath, found: list[Violation]) -> None:
    if node.variable is not None:
        found.append(_at(node, "variable", node.variable))
    for segment in node.compiled.segments:
        for selector in segment.selectors:
            if isinstance(selector, PathFunctionSelector):
                found.append(_at(node, "fonction_de_chemin", selector.name))
            elif isinstance(selector, FilterSelector):
                _filter(node, selector.expression, found)


def _filter(node: JsltPath, expression: FilterExpression, found: list[Violation]) -> None:
    """`?(...)` : un seul prédicat, clos sur l'élément filtré (`@`) et des constantes."""
    if isinstance(expression, FilterPath):
        # Test d'existence `?(@.x)` : un prédicat à lui seul.
        _closed(node, expression, found)
        return
    if not isinstance(expression, FilterBinary) or expression.operator not in FILTER_COMPARISONS:
        found.append(_at(node, "predicat", "une seule comparaison attendue"))
        return
    for side in (expression.left, expression.right):
        if isinstance(side, FilterPath):
            _closed(node, side, found)
        elif not isinstance(side, FilterLiteral):
            found.append(_at(node, "predicat_non_clos", "chemin ou constante attendu"))


def _closed(node: JsltPath, side: FilterPath, found: list[Violation]) -> None:
    # Clos : le prédicat ne regarde que l'élément filtré. Un `$` relirait le document
    # entier, et le résultat d'un filtre dépendrait d'ailleurs que de ce qu'il filtre.
    if not side.is_current:
        found.append(_at(node, "predicat_non_clos", "chemin relatif à @ attendu"))


def unknown_functions(ast: JsltBase, registry: FunctionRegistry) -> tuple[Violation, ...]:
    """Fonctions appelées que le catalogue ne connaît pas : refusées à l'écriture.

    Vérifiées ici plutôt qu'à l'exécution : une fonction retirée du registre rend
    ses templates invalides dès leur prochaine vérification, pas sur un terminal.
    """
    found: list[Violation] = []
    _calls(ast, registry, found)
    return tuple(found)


def _calls(node: JsltBase, registry: FunctionRegistry, found: list[Violation]) -> None:
    if isinstance(node, JsltFunctionCall) and node.name not in registry:
        found.append(_at(node, "fonction_inconnue", node.name))
    for child in _children(node):
        _calls(child, registry, found)


def _children(node: JsltBase) -> list[JsltBase]:
    children: list[JsltBase | None] = []
    if isinstance(node, JsltObject):
        children += [node.source, node.where, *node.variables, *node.properties]
    elif isinstance(node, JsltProperty):
        children.append(node.value)
    elif isinstance(node, JsltArray):
        children += node.items
    elif isinstance(node, JsltFunctionCall):
        children += node.arguments
    elif isinstance(node, JsltBinaryOperator):
        children += [node.left, node.right]
    elif isinstance(node, JsltOperator):
        children.append(node.left)
    elif isinstance(node, JsltSwitch):
        children += [node.expression, node.default, *node.cases]
    return [c for c in children if c is not None]
