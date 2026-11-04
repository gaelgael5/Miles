from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from urban_json import FunctionRegistry

from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import entry_of
from miles.datamodels.schema import parse_schema
from miles.git.worktree import MANIFEST


@dataclass(frozen=True)
class FunctionEntry:
    name: str
    signature: str
    description: str
    # Docstring entière : comportement et cas limites, pas seulement le nom.
    documentation: str
    parameters: tuple[dict[str, Any], ...]
    returns: str | None
    # Vide : documentée. Sinon ce qui manque ; une telle entrée n'est pas présentée
    # comme utilisable (critère 6).
    missing: tuple[str, ...]


_DERIVED_RE = re.compile(
    r"^contracts/(?P<slug>[^/]+)/models/v(?P<number>\d+)/(?P<name>[^/]+)\.yaml$"
)


@dataclass(frozen=True)
class ModelCatalogEntry:
    scope: str
    name: str
    path: str
    # None : le modèle ne passe pas sa grammaire ; la validation de la branche dit pourquoi.
    properties: tuple[dict[str, Any], ...] | None


def functions_catalog(registry: FunctionRegistry) -> list[FunctionEntry]:
    """Dérivé du registre que le moteur évalue : aucune liste tenue à la main."""
    entries = []
    for info in registry.describe_all():
        documentation = inspect.getdoc(info.function) or ""
        missing = []
        if not info.description.strip() or not documentation.strip():
            missing.append("description")
        if any(p.type is None for p in info.parameters):
            missing.append("types")
        entries.append(
            FunctionEntry(
                info.name,
                info.signature(),
                info.description,
                documentation,
                tuple(p.to_dict() for p in info.parameters),
                info.returns,
                tuple(missing),
            )
        )
    return sorted(entries, key=lambda e: e.name)


async def models_catalog(
    paths: list[str], read: Callable[[str], Awaitable[str | None]]
) -> list[ModelCatalogEntry]:
    entries = []
    for entry in filter(None, map(entry_of, paths)):
        text = await read(entry.path)
        entries.append(ModelCatalogEntry(entry.scope, entry.name, entry.path, _properties(text)))
    # Les modèles dérivés des contrats (story 47f55d8b), portée « contracts/<slug>/v<n> » :
    # ce sont les entrées et sorties des templates vers et depuis un tiers.
    for path in paths:
        match = _DERIVED_RE.match(path)
        if match is not None:
            scope = f"contracts/{match['slug']}/v{match['number']}"
            properties = _derived_properties(await read(path))
            entries.append(ModelCatalogEntry(scope, match["name"], path, properties))
    return entries


def _derived_properties(text: str | None) -> tuple[dict[str, Any], ...] | None:
    # Un modèle dérivé n'est pas forcément un objet (une énumération du contrat) : ses
    # propriétés se lisent sans la règle « racine objet » des pivots.
    try:
        data = load_yaml(text) if text is not None else None
    except ValueError:
        return None
    declared = data.get("properties") if isinstance(data, dict) else None
    if not isinstance(declared, dict):
        return () if isinstance(data, dict) else None
    return tuple({"name": name} | dict(spec) for name, spec in declared.items())


def _properties(text: str | None) -> tuple[dict[str, Any], ...] | None:
    if text is None:
        return None
    try:
        declared = parse_schema(text).properties
    except ValueError:
        return None
    # Le schéma de chaque propriété, tel que JSON Schema le décrit (story 0f7cda10).
    return tuple({"name": name} | dict(spec) for name, spec in declared.items())


async def app_floor(read: Callable[[str], Awaitable[str | None]]) -> str | None:
    """Plancher de version d'application déclaré par la branche (Gael, 22/10/2026).

    C'est contre lui que s'écrit un template destiné au terminal : il fonctionne sur
    tout terminal à jour de ce plancher. None : pas encore déclaré.
    """
    text = await read(MANIFEST)
    try:
        data = json.loads(text) if text is not None else {}
    except json.JSONDecodeError:
        return None
    floor = data.get("min_app_version") if isinstance(data, dict) else None
    return floor if isinstance(floor, str) else None
