from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from urllib.parse import urlsplit

from urban_json import (
    FunctionRegistry,
    JsltError,
    JsltSemanticError,
    JsltSyntaxError,
    default_registry,
)
from urban_json.ast import JsltBase
from urban_json.ast.nodes import JsltFunctionCall, JsltPath
from urban_json.parsing import parse_to_tree
from urban_json.parsing.script_builder_visitor import ScriptBuilderVisitor
from urban_json.runtime import JsltEvaluationVisitor, RuntimeContext, Sources

from miles.transform.profile import Violation, check_profile, unknown_functions

CAST_FUNCTION = "convert"
_CORE_MODULE = "urban_json.functions."
_CAST_DESCRIPTION = (
    "Convertit une valeur selon un suffixe #type (integer, decimal, boolean, string,"
    " datetime, time, uuid, uri). Une valeur absente reste absente ; une valeur"
    " incompatible est une erreur nommant le chemin, jamais une valeur par défaut."
)


class TemplateSyntaxError(Exception):
    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


class OutsideProfileError(Exception):
    """Template lisible mais hors profil : toutes les constructions fautives, situées."""

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        super().__init__(f"{len(violations)} construction(s) hors profil")
        self.violations = violations


class UnsupportedConstructError(Exception):
    """Lisible par la grammaire du moteur, mais pas encore construite par lui.

    Le cas mesuré le 31/10/2026 : `nin`, `contains`, `size` et `empty` dans un filtre
    `[?(…)]`. La grammaire les ANNONCE — le message d'erreur du moteur les liste comme
    attendus — et le constructeur d'AST lève `NotImplementedError` dessus. Sans cette
    reprise, l'exception traversait Miles jusqu'à un 500 : une saisie de l'utilisateur
    ne doit jamais produire une erreur serveur, elle produit un refus qui la nomme.

    Distincte de `TemplateSyntaxError` : le texte n'a rien de fautif, c'est le moteur
    qui ne sait pas encore le faire. Le jour où il saura, le refus disparaîtra de
    lui-même sans qu'on touche à Miles.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EvaluationError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        path: str | None = None,
        expected: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code, self.message, self.path, self.expected = code, message, path, expected


class _CastError(Exception):
    def __init__(self, expected: str) -> None:
        super().__init__(expected)
        self.expected = expected


class _BudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Template:
    source: str
    ast: JsltBase


def parse_ast(source: str) -> JsltBase:
    """Arbre du moteur pour ce texte, sans aucune vérification de profil."""
    try:
        ast: JsltBase = ScriptBuilderVisitor().visit(parse_to_tree(source))
    except JsltSyntaxError as exc:
        raise TemplateSyntaxError(str(exc), exc.line, exc.column) from None
    except JsltSemanticError as exc:
        location = exc.location
        raise TemplateSyntaxError(
            str(exc), getattr(location, "line", None), getattr(location, "column", None)
        ) from None
    except NotImplementedError as exc:
        # Attrapée ICI et nulle part ailleurs : le constructeur d'AST du moteur lève
        # `NotImplementedError` sur ce que sa grammaire accepte mais qu'il ne sait pas
        # encore bâtir. C'est une saisie de l'utilisateur, donc un REFUS — jamais une
        # erreur serveur. La portée est étroite exprès : la seule chose enveloppée est
        # l'analyse d'un texte que la personne vient de taper.
        raise UnsupportedConstructError(str(exc)) from None
    return ast


def compile_template(source: str) -> Template:
    """Analyse le template et le confronte au profil ; refuse ce qui n'y entre pas."""
    ast = parse_ast(source)
    violations = check_profile(ast) + unknown_functions(ast, function_registry())
    if violations:
        raise OutsideProfileError(violations)
    return Template(source, ast)


def evaluate(template: Template, document: Any, budget: int) -> Any:
    """Applique le template ; toute erreur est explicite, jamais un résultat partiel."""
    # Sans message, la source vaut {} (Gael, 22/10/2026 : chaîne de transformations).
    # Cela remplace le refus d'une entrée vide d'abord livré (68cae2ff, critère 8) : un
    # template de constantes ou d'appels de fonctions sur {} est légitime.
    if document is None:
        document = {}
    evaluator = _Evaluator(RuntimeContext(Sources(document), function_registry()), budget)
    try:
        return template.ast.accept(evaluator)
    except _BudgetExceeded:
        raise EvaluationError("budget_depasse", expected=str(budget)) from None
    except EvaluationError:
        raise
    except (JsltError, ValueError, TypeError) as exc:
        raise EvaluationError("evaluation", str(exc)) from None


class _Evaluator(JsltEvaluationVisitor):
    """Évaluateur du moteur, borné en nombre de nœuds évalués.

    La sémantique n'est pas touchée : seules s'ajoutent la borne et la désignation du
    chemin fautif d'une conversion. Le langage n'a pas de boucle, mais `$source` itère
    sur les données : un document énorme ferait tourner un template sans fin visible.
    """

    def __init__(self, context: RuntimeContext, budget: int) -> None:
        super().__init__(context)
        self._remaining = budget
        for name in dir(JsltEvaluationVisitor):
            if name.startswith("visit_"):
                setattr(self, name, self._counted(getattr(self, name)))

    def _counted(self, visit: Callable[[Any], Any]) -> Callable[[Any], Any]:
        def counted(node: Any) -> Any:
            self._remaining -= 1
            if self._remaining < 0:
                raise _BudgetExceeded
            return visit(node)

        return counted

    def visit_function(self, node: JsltFunctionCall) -> Any:
        try:
            return super().visit_function(node)
        except _CastError as exc:
            target = node.arguments[0] if node.arguments else None
            path = target.value if isinstance(target, JsltPath) else None
            raise EvaluationError("conversion", path=path, expected=exc.expected) from None


def function_registry() -> FunctionRegistry:
    """Le registre unique de Miles : celui qu'évalue le moteur et que décrit le catalogue."""
    return _REGISTRY


def _registry() -> FunctionRegistry:
    """Registre de Miles : les fonctions cœur du moteur, et sa conversion stricte.

    Isolé, jamais le registre par défaut du moteur lui-même, que `load_plugins` peut
    avoir garni de tout plugin installé (HTTP, SQL…). Seules entrent les fonctions
    définies dans le paquet `urban_json.functions` (Gael, 22/10/2026) : un plugin
    installé plus tard ne s'y glisse pas. Le catalogue dérive de ce registre.
    """
    registry = FunctionRegistry()
    for name in default_registry.names():
        function = default_registry.get(name)
        info = default_registry.describe(name)
        if function is None or info is None:
            continue
        if not function.__module__.startswith(_CORE_MODULE):
            continue
        registry.register(name, function, info.path_args, info.description)
    # Écart voulu au convert du moteur (voir _strict_convert) : il le remplace.
    registry.register(CAST_FUNCTION, _strict_convert, (), _CAST_DESCRIPTION)
    return registry


def _strict_convert(ctx: Any, value: Any = None, target: str = "string") -> Any:
    """Conversion sans valeur de secours : incompatible, c'est une erreur (critère 7).

    Écart voulu au `convert` du moteur, qui rend 0, "" ou faux pour une valeur absente
    et sérialise un objet en chaîne : un mapping faux passerait alors sans erreur.
    """
    if value is None:
        # Absent reste absent : c'est à `??` de fournir une valeur, explicitement.
        return None
    if isinstance(value, (dict, list)):
        raise _CastError(target)
    converter = _CONVERTERS.get(target)
    if converter is None:
        raise _CastError(target)
    try:
        return converter(value)
    except (ValueError, TypeError):
        raise _CastError(target) from None


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError
        return int(value)
    return int(value) if isinstance(value, int) else int(str(value).strip())


def _decimal(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError
    return float(value) if isinstance(value, (int, float)) else float(str(value).strip())


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if isinstance(value, str) else None
    if text in ("true", "false"):
        return text == "true"
    raise ValueError


def _string(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _uri(value: str) -> None:
    # Une URI porte au moins un schéma ; « colis/42 » n'en est pas une.
    if not urlsplit(value).scheme:
        raise ValueError


def _checked(parse: Callable[[str], Any]) -> Callable[[Any], str]:
    def convert(value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError
        parse(value)
        return value

    return convert


_CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "integer": _integer,
    "decimal": _decimal,
    "boolean": _boolean,
    "string": _string,
    "datetime": _checked(datetime.fromisoformat),
    "time": _checked(time.fromisoformat),
    "uuid": _checked(uuid.UUID),
    "uri": _checked(_uri),
}

# Construit une fois : les fonctions viennent du code installé, pas d'une configuration.
_REGISTRY = _registry()
