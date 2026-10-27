from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from miles.contracts.layout import contract_dir
from miles.datamodels.grammar import Problem
from miles.datamodels.schema import DIALECT, ID_PREFIX
from miles.workshop.reading import Read
from miles.workspaces.model import WorkspaceInputError

# Modèles dérivés d'une version de contrat (story 47f55d8b, Gael, 23/10/2026) : un par
# schéma de `components/schemas`, en JSON Schema 2020-12, écrits dans git sous le contrat
# et jamais édités — un contrat est subi.
MODELS_DIR = "models"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_SCHEMA_REF = "#/components/schemas/"
# Mots-clés dont la valeur est un schéma, une liste ou une table de schémas : seuls eux
# se convertissent. Une propriété nommée « example » ou « nullable » est un nom, pas un
# mot-clé ; un parcours aveugle du document la réécrirait.
_ONE = (
    "items",
    "additionalProperties",
    "not",
    "if",
    "then",
    "else",
    "contains",
    "propertyNames",
    "unevaluatedItems",
    "unevaluatedProperties",
)
_MANY = ("allOf", "anyOf", "oneOf", "prefixItems")
_TABLE = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
# Borne de la descente : un schéma de tiers démesurément imbriqué est refusé, nommé,
# plutôt que d'épuiser la pile du back-office.
MAX_DEPTH = 64
_META = Draft202012Validator(Draft202012Validator.META_SCHEMA)


@dataclass(frozen=True)
class DerivedModel:
    name: str
    # Le nom du schéma dans le contrat, avant normalisation.
    source: str
    path: str
    content: str


class DerivationError(ValueError):
    """Un ou plusieurs schémas du contrat ne se convertissent pas : rien n'est écrit."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} schéma(s) non convertible(s)")
        self.problems = problems


def models_dir(slug: str, number: int) -> str:
    return f"{contract_dir(slug)}/{MODELS_DIR}/v{number}"


def derived_id(slug: str, number: int, name: str) -> str:
    return f"{ID_PREFIX}contracts/{slug}/v{number}/{name}"


def model_name(schema: str) -> str | None:
    """Le nom de modèle d'un schéma : `PickupPoint` → `pickup-point` ; None s'il n'en a pas."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", schema).lower()
    name = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9_-]", "-", spaced)).strip("-_")[:63]
    return name if _NAME_RE.match(name) else None


def checked_model_name(name: str) -> str:
    # Le nom devient un segment de chemin : refusé avant tout accès au dépôt.
    if not _NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name


def derive_models(data: dict[str, Any], slug: str, number: int) -> list[DerivedModel]:
    """Les modèles d'une version de contrat ; lève DerivationError avec tous les écarts."""
    schemas = (data.get("components") or {}).get("schemas") or {}
    names, problems = _names(schemas)
    legacy = str(data.get("openapi", "")).startswith("3.0")
    models = []
    for source, schema in sorted(schemas.items()):
        where = f"components.schemas.{source}"
        converter = _Converter(names, slug, number, legacy, problems)
        body = converter.schema(schema, where, 0)
        if source not in names or not isinstance(body, dict):
            continue
        name = names[source]
        head = {"$schema": DIALECT, "$id": derived_id(slug, number, name)}
        body = {"title": source} | {k: v for k, v in body.items() if k not in head}
        problems += [
            Problem(where, "schema_invalide", error.message) for error in _META.iter_errors(body)
        ]
        content = yaml.safe_dump(head | body, allow_unicode=True, sort_keys=False)
        models.append(
            DerivedModel(name, source, f"{models_dir(slug, number)}/{name}.yaml", content)
        )
    if problems:
        raise DerivationError(problems)
    return models


def _names(schemas: Any) -> tuple[dict[str, str], list[Problem]]:
    names: dict[str, str] = {}
    problems = []
    taken: dict[str, str] = {}
    for source in sorted(schemas):
        name = model_name(source)
        where = f"components.schemas.{source}"
        if name is None:
            problems.append(Problem(where, "nom_de_schema_inconvertible", source))
        elif name in taken:
            # Deux schémas, un seul fichier : on refuse plutôt que d'en écraser un.
            problems.append(Problem(where, "noms_de_schema_en_collision", taken[name]))
        else:
            taken[name] = source
            names[source] = name
    return names, problems


@dataclass
class _Converter:
    names: dict[str, str]
    slug: str
    number: int
    # OpenAPI 3.0 : son dialecte n'est pas JSON Schema 2020-12 et se convertit ; un 3.1
    # l'est déjà, seuls ses `$ref` se réécrivent.
    legacy: bool
    problems: list[Problem]

    def schema(self, node: Any, where: str, depth: int) -> Any:
        if depth > MAX_DEPTH:
            self.problems.append(Problem(where, "schema_trop_profond", str(MAX_DEPTH)))
            return node
        if not isinstance(node, dict):
            return node
        out = {key: self._value(key, value, where, depth) for key, value in node.items()}
        if isinstance(out.get("$ref"), str):
            out["$ref"] = self._ref(out["$ref"], where)
        return self._dialect(out, where) if self.legacy else out

    def _value(self, key: str, value: Any, where: str, depth: int) -> Any:
        inner = f"{where}.{key}"
        if key in _ONE:
            return self.schema(value, inner, depth + 1)
        if key in _MANY and isinstance(value, list):
            return [self.schema(v, f"{inner}.{i}", depth + 1) for i, v in enumerate(value)]
        if key in _TABLE and isinstance(value, dict):
            return {k: self.schema(v, f"{inner}.{k}", depth + 1) for k, v in value.items()}
        return value

    def _ref(self, ref: str, where: str) -> str:
        if not ref.startswith(_SCHEMA_REF):
            # Seuls les schémas du contrat deviennent des modèles : un `$ref` vers un
            # paramètre ou une réponse n'aurait rien à désigner.
            self.problems.append(Problem(f"{where}.$ref", "reference_non_convertible", ref))
            return ref
        target, _, rest = ref.removeprefix(_SCHEMA_REF).partition("/")
        target = target.replace("~1", "/").replace("~0", "~")
        name = self.names.get(target)
        if name is None:
            self.problems.append(Problem(f"{where}.$ref", "reference_non_convertible", ref))
            return ref
        uri = derived_id(self.slug, self.number, name)
        return f"{uri}#/{rest}" if rest else uri

    def _dialect(self, node: dict[str, Any], where: str) -> dict[str, Any]:
        """OpenAPI 3.0 → JSON Schema 2020-12, sans perte de sens, ou un écart nommé."""
        for bound in ("Minimum", "Maximum"):
            exclusive, inclusive = f"exclusive{bound}", bound.lower()
            flag = node.get(exclusive)
            if isinstance(flag, bool):
                del node[exclusive]
                if flag and inclusive not in node:
                    self.problems.append(
                        Problem(f"{where}.{exclusive}", "borne_exclusive_sans_borne")
                    )
                elif flag:
                    node[exclusive] = node.pop(inclusive)
        if "example" in node:
            node["examples"] = [node.pop("example")]
        nullable = node.pop("nullable", False)
        if nullable is not True:
            return node
        kind = node.get("type")
        if isinstance(kind, str):
            node["type"] = [kind, "null"]
            if isinstance(node.get("enum"), list) and None not in node["enum"]:
                # `enum` restreint aussi null : sans lui, la valeur nulle serait refusée.
                node["enum"] = [*node["enum"], None]
            return node
        # Sans type (un `$ref`, une composition) : null s'ajoute en alternative.
        return {"anyOf": [node, {"type": "null"}]}


# État des modèles dérivés d'une version dans git, comparés à ce que donne son fichier.
UP_TO_DATE = "a_jour"
STALE = "a_rederiver"
UNDERIVABLE = "non_derivable"


@dataclass(frozen=True)
class DerivedState:
    state: str
    # Noms des modèles présents dans git pour cette version.
    present: tuple[str, ...]
    # Écarts de dérivation quand la version n'est pas dérivable ; sinon vide.
    problems: tuple[Problem, ...] = ()


def present_models(paths: list[str], slug: str, number: int) -> dict[str, str]:
    """Nom → chemin des modèles dérivés présents dans git pour la version."""
    prefix = f"{models_dir(slug, number)}/"
    found = {}
    for path in paths:
        rest = path.removeprefix(prefix)
        if path.startswith(prefix) and "/" not in rest and rest.endswith(".yaml"):
            found[rest.removesuffix(".yaml")] = path
    return found


async def derived_state(
    read: Read, paths: list[str], slug: str, number: int, document: dict[str, Any]
) -> DerivedState:
    """Les modèles de la version sont-ils exactement ce que donne son fichier ?

    Retouchés à la main dans git, absents (version intégrée avant la story 47f55d8b) ou en
    trop, ils ne disent plus ce que dit le contrat : « à redériver ».
    """
    present = present_models(paths, slug, number)
    names = tuple(sorted(present))
    try:
        expected = derive_models(document, slug, number)
    except DerivationError as exc:
        return DerivedState(UNDERIVABLE, names, tuple(exc.problems))
    if {m.name for m in expected} != set(present):
        return DerivedState(STALE, names)
    for model in expected:
        if await read(model.path) != model.content:
            return DerivedState(STALE, names)
    return DerivedState(UP_TO_DATE, names)
