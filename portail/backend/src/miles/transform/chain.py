from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from urban_json.ast.nodes import JsltObject, JsltPath
from urban_json.jsonpath import IndexSelector, NameSelector, PathScope

from miles.transform.engine import (
    EvaluationError,
    OutsideProfileError,
    Template,
    TemplateSyntaxError,
    compile_template,
    evaluate,
    parse_ast,
)
from miles.transform.profile import Violation

# Chaîne de transformations (story 66ae5c10, Gael 22/10/2026) : des étapes ordonnées par
# l'utilisateur, appliquées au même message aux quatre points de passage (source de
# données, MQTT vers l'appareil, MQTT depuis l'appareil, webservices externes).


@dataclass(frozen=True)
class StepSpec:
    template: str
    # Vide : le résultat du template devient le message. Sinon, un chemin unique où le
    # poser dans le message source.
    target: str | None = None


@dataclass(frozen=True)
class StepProblem:
    """Ce qui empêche d'écrire une étape, avec son rang (0 pour la première)."""

    step: int
    code: str
    detail: str | None = None
    violations: tuple[Violation, ...] = ()
    line: int | None = None
    column: int | None = None


class ChainInvalidError(Exception):
    def __init__(self, problems: list[StepProblem]) -> None:
        super().__init__(f"{len(problems)} étape(s) en défaut")
        self.problems = problems


class ChainFailedError(Exception):
    """Une étape a échoué : la chaîne entière échoue, rien n'en sort (critère 6)."""

    def __init__(self, step: int, cause: EvaluationError) -> None:
        super().__init__(f"étape {step} : {cause.code}")
        self.step, self.cause = step, cause


@dataclass(frozen=True)
class _Target:
    text: str
    # Noms (str) et indices (int), du document vers l'endroit visé.
    keys: tuple[str | int, ...]


@dataclass(frozen=True)
class _Step:
    template: Template
    target: _Target | None


@dataclass(frozen=True)
class Chain:
    steps: tuple[_Step, ...]


def compile_chain(specs: list[StepSpec]) -> Chain:
    """Vérifie toutes les étapes ; rend tous les écarts, chacun avec son rang."""
    steps: list[_Step] = []
    problems: list[StepProblem] = []
    for rank, spec in enumerate(specs):
        template = _template(rank, spec.template, problems)
        target = _target(rank, spec.target, problems)
        if template is not None:
            steps.append(_Step(template, target))
    if problems:
        raise ChainInvalidError(problems)
    return Chain(tuple(steps))


def run_chain(chain: Chain, message: Any, budget: int) -> list[Any]:
    """Applique la chaîne ; rend le message produit après chaque étape (critère 9).

    Le dernier élément est le message final ; une chaîne vide rend le message tel quel.
    """
    # Sans message, la source vaut {} (Gael) : un template de constantes ou de
    # fonctions de référentiel produit alors un message à partir de rien.
    current: Any = {} if message is None else message
    produced = []
    for rank, step in enumerate(chain.steps):
        try:
            result = evaluate(step.template, current, budget)
            current = result if step.target is None else _project(current, step.target, result)
        except EvaluationError as exc:
            raise ChainFailedError(rank, exc) from None
        produced.append(current)
    return produced or [current]


def _template(rank: int, source: str, problems: list[StepProblem]) -> Template | None:
    try:
        return compile_template(source)
    except TemplateSyntaxError as exc:
        problems.append(StepProblem(rank, "syntaxe", exc.message, line=exc.line, column=exc.column))
    except OutsideProfileError as exc:
        problems.append(StepProblem(rank, "hors_profil", violations=exc.violations))
    return None


def _target(rank: int, raw: str | None, problems: list[StepProblem]) -> _Target | None:
    text = (raw or "").strip()
    if not text:
        return None
    keys = _singular_keys(text)
    if keys is None:
        problems.append(StepProblem(rank, "cible_invalide", text))
        return None
    return _Target(text, keys)


def _singular_keys(text: str) -> tuple[str | int, ...] | None:
    """Le chemin, s'il désigne un seul endroit à partir de la racine ; None sinon.

    Lu par le parseur du moteur, dans un template minimal : jamais par une expression
    maison, qui finirait par accepter ce que le moteur comprend autrement.
    """
    try:
        ast = parse_ast(f'{{ "cible": {text} }}')
    except TemplateSyntaxError:
        return None
    if not isinstance(ast, JsltObject):
        return None
    values = [p.value for p in ast.properties]
    path = values[0] if len(values) == 1 else None
    if not isinstance(path, JsltPath) or path.variable is not None:
        return None
    compiled = path.compiled
    if compiled.scope is not PathScope.GLOBAL or not compiled.segments or not compiled.is_singular:
        return None
    keys: list[str | int] = []
    for segment in compiled.segments:
        selector = segment.selectors[0]
        if isinstance(selector, NameSelector):
            keys.append(selector.name)
        elif isinstance(selector, IndexSelector):
            keys.append(selector.index)
        else:
            return None
    return tuple(keys)


def _project(message: Any, target: _Target, value: Any) -> Any:
    """Pose `value` au chemin cible d'une copie du message, objets intermédiaires créés.

    Un nom traversé qui ne porte pas un objet (un texte, un nombre, null) est écrasé par
    un objet (Gael, 22/10/2026 : « la valeur est écrasée »). Un indice, lui, ne se crée
    pas : poser `$.lignes[3]` dans un tableau de deux éléments reste une erreur.
    """
    # Copie : le message d'une étape reste intact si la projection échoue plus loin.
    root = copy.deepcopy(message)
    if isinstance(target.keys[0], str) and not isinstance(root, dict):
        root = {}
    node = root
    for depth, key in enumerate(target.keys):
        following = target.keys[depth + 1] if depth + 1 < len(target.keys) else None
        if isinstance(key, int) and (
            not isinstance(node, list) or not -len(node) <= key < len(node)
        ):
            raise EvaluationError("cible_impossible", path=target.text)
        if following is None:
            node[key] = value
            break
        child = node.get(key) if isinstance(node, dict) else node[key]
        if isinstance(following, str) and not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    return root
