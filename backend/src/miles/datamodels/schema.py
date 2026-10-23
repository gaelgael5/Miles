from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml

# Les modèles de données sont des JSON Schema 2020-12 écrits en YAML (Gael, 23/10/2026,
# story 0f7cda10) : le standard d'OpenAPI 3.1, lu par tous et connu de l'agent.
DIALECT = "https://json-schema.org/draft/2020-12/schema"
# Un modèle se désigne par un URI absolu, indépendant de l'emplacement de celui qui le
# désigne : un chemin relatif casserait au moindre déplacement et serait illisible.
ID_PREFIX = "miles:/"
_ID_RE = re.compile(
    r"^miles:/(?:shared/(?P<shared>[a-z0-9][a-z0-9_-]*)"
    r"|domains/(?P<domain>[a-z0-9][a-z0-9_-]*)/(?P<name>[a-z0-9][a-z0-9_-]*))$"
)
_META = Draft202012Validator(Draft202012Validator.META_SCHEMA)


@dataclass(frozen=True)
class ModelSchema:
    title: str | None
    # L'`$id` tel qu'écrit ; le système le pose, la validation de la branche le vérifie.
    identifier: str | None
    # Propriétés de premier niveau, telles que le schéma les déclare.
    properties: dict[str, Any]
    # (chemin dans le document, (portée, nom)) de chaque `$ref` vers un autre modèle.
    references: tuple[tuple[str, tuple[str, str]], ...] = field(default=())
    # Aucune propriété encore : un brouillon, admis à l'écriture mais pas dans une
    # version de la branche (Gael, 23/10/2026).
    empty: bool = False


def model_id(scope: str, name: str) -> str:
    if scope == "shared":
        return f"{ID_PREFIX}shared/{name}"
    return f"{ID_PREFIX}domains/{scope}/{name}"


def target_of(ref: str) -> tuple[str, str] | None:
    """(portée, nom) d'un `$ref` vers un modèle ; None s'il n'en désigne pas un."""
    match = _ID_RE.match(ref.split("#", 1)[0])
    if match is None:
        return None
    if match["shared"] is not None:
        return "shared", match["shared"]
    return match["domain"], match["name"]


def _where(path: Any) -> str:
    return ".".join(str(part) for part in path)


def _refs(node: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield _where((*path, "$ref")), ref
        for key, value in node.items():
            yield from _refs(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _refs(value, (*path, index))


def _resolves(root: Any, ref: str) -> bool:
    """Le pointeur JSON `#/…` désigne-t-il un nœud du document ?"""
    fragment = ref.removeprefix("#")
    if fragment == "":
        return True
    if not fragment.startswith("/"):
        return False
    node = root
    for part in fragment[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    return True


def parse_schema(text: str) -> ModelSchema:
    """Lit et vérifie un modèle ; lève ModelSyntaxError ou ModelGrammarError (tous les écarts)."""
    data = load_yaml(text)
    if not isinstance(data, dict):
        raise ModelGrammarError([Problem("", "document_non_objet")])
    problems = [
        Problem(_where(error.absolute_path), "schema_invalide", error.message)
        for error in sorted(_META.iter_errors(data), key=lambda e: list(map(str, e.path)))
    ]
    # Règles propres à Miles, en plus du méta-schéma : un modèle décrit un objet, et ne
    # désigne que des modèles de Miles ou ses propres définitions (#/…).
    if data.get("type") != "object":
        problems.append(Problem("type", "objet_attendu"))
    references = []
    for where, ref in _refs(data):
        target = target_of(ref)
        if target is not None:
            references.append((where, target))
        elif not ref.startswith("#"):
            problems.append(Problem(where, "reference_externe", ref))
        elif not _resolves(data, ref):
            # Une référence interne qui ne désigne rien passe le méta-schéma ; elle
            # casserait à l'usage (ex. « #miles:/… », un URI collé derrière le « # »).
            problems.append(Problem(where, "reference_interne_introuvable", ref))
    if problems:
        raise ModelGrammarError(problems)
    properties = data.get("properties") or {}
    title = data.get("title")
    identifier = data.get("$id")
    return ModelSchema(
        title if isinstance(title, str) and title.strip() else None,
        identifier if isinstance(identifier, str) else None,
        dict(properties) if isinstance(properties, dict) else {},
        tuple(references),
        not properties,
    )


def normalized(text: str, scope: str, name: str) -> str:
    """Le schéma tel que Miles l'enregistre : `$schema` et `$id` posés par le système.

    Réécrit en entier, clés de tête d'abord : les commentaires du YAML ne survivent pas,
    ce que l'éditeur visuel impose de toute façon (le schéma y est un objet).
    """
    data = load_yaml(text)
    if not isinstance(data, dict):
        raise ModelGrammarError([Problem("", "document_non_objet")])
    head = {"$schema": DIALECT, "$id": model_id(scope, name)}
    rest = {k: v for k, v in data.items() if k not in head}
    return yaml.safe_dump(head | rest, allow_unicode=True, sort_keys=False)


def draft(scope: str, name: str, title: str) -> str:
    """Le schéma d'un modèle tout juste déclaré : un objet sans propriété."""
    body = {"title": title, "type": "object", "properties": {}}
    return normalized(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), scope, name)


def references_in(text: str) -> set[tuple[str, str]]:
    """Modèles désignés par un document, même non conforme : pour protéger la suppression.

    Repli volontaire et tolérant : un fichier retouché à la main hors de Miles doit encore
    compter comme référençant, plutôt que laisser supprimer ce qu'il désigne.
    """
    try:
        data = load_yaml(text)
    except ValueError:
        return set()
    return {t for _, ref in _refs(data) if (t := target_of(ref)) is not None}
