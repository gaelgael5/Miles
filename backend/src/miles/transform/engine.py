from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from urllib.parse import urlsplit

from urban_json import FunctionRegistry, JsltError, JsltSemanticError, JsltSyntaxError
from urban_json.ast import JsltBase
from urban_json.ast.nodes import JsltFunctionCall, JsltPath
from urban_json.parsing import parse_to_tree
from urban_json.parsing.script_builder_visitor import ScriptBuilderVisitor
from urban_json.runtime import JsltEvaluationVisitor, RuntimeContext, Sources

from miles.transform.profile import Violation, check_profile

CAST_FUNCTION = "convert"


class TemplateSyntaxError(Exception):
    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


class OutsideProfileError(Exception):
    """Template lisible mais hors profil : toutes les constructions fautives, situées."""

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        super().__init__(f"{len(violations)} construction(s) hors profil")
        self.violations = violations


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


def compile_template(source: str) -> Template:
    """Analyse le template et le confronte au profil ; refuse ce qui n'y entre pas."""
    try:
        ast = ScriptBuilderVisitor().visit(parse_to_tree(source))
    except JsltSyntaxError as exc:
        raise TemplateSyntaxError(str(exc), exc.line, exc.column) from None
    except JsltSemanticError as exc:
        location = exc.location
        raise TemplateSyntaxError(
            str(exc), getattr(location, "line", None), getattr(location, "column", None)
        ) from None
    violations = check_profile(ast)
    if violations:
        raise OutsideProfileError(violations)
    return Template(source, ast)


def evaluate(template: Template, document: Any, budget: int) -> Any:
    """Applique le template ; toute erreur est explicite, jamais un résultat partiel."""
    # Entrée vide ou absente : refusée plutôt que transformée en un document creux,
    # qui passerait pour un résultat (critère 8).
    if document is None or document == {} or document == []:
        raise EvaluationError("entree_vide")
    evaluator = _Evaluator(RuntimeContext(Sources(document), _registry()), budget)
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


def _registry() -> FunctionRegistry:
    # Registre isolé, jamais le registre par défaut du moteur : celui-ci charge tout
    # plugin installé (HTTP, SQL…). Le catalogue (ticket 28f00c74) y ajoutera ses
    # fonctions ; d'ici là, seule la conversion des suffixes `#type`.
    registry = FunctionRegistry()
    registry.register(CAST_FUNCTION, _strict_convert, (), "Conversion stricte d'un #type")
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
