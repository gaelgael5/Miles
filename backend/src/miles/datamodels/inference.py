"""Déduction d'un schéma depuis un échantillon de document (Gael, 24/10/2026).

Sert l'« import intelligent » de l'écran : on colle un bout de JSON ou de YAML, et Miles
en tire la forme. Côté serveur et non dans l'écran, parce que c'est de la logique de
modèle : le serveur est déjà l'arbitre de ce qu'est un schéma valide, et la surface MCP
pourra s'en servir sans réécrire la règle.

Deux partis pris, demandés par Gael le 24/10/2026 :

- **`required` reste vide.** Un échantillon est UN cas, pas le contrat. Une clé vue là
  n'est pas forcément exigée, une clé absente n'est pas interdite. On décrit les types,
  et c'est la personne qui coche ensuite ce qui est réellement obligatoire.
- **Les formats de chaîne sont devinés** (date, date-time, e-mail, uuid). On accepte le
  faux positif — un identifiant en forme d'uuid recevra `format: uuid` — parce que le
  schéma produit est un brouillon qu'on relit, jamais un contrat déjà publié.
"""

from __future__ import annotations

import json
import re
from typing import Any

from miles.datamodels.grammar import ModelSyntaxError, load_yaml

JSON_FORMAT = "json"
YAML_FORMAT = "yaml"
FORMATS = (JSON_FORMAT, YAML_FORMAT)

# Formats reconnus, du plus spécifique au plus général : « date-time » doit passer avant
# « date », dont il contient la forme.
_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "date-time",
        re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})?$"),
    ),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("time", re.compile(r"^\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})?$")),
    (
        "uuid",
        re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    ),
    ("email", re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")),
    ("uri", re.compile(r"^https?://[^\s]+$")),
)


def read_sample(text: str, fmt: str) -> Any:
    """L'échantillon désérialisé ; lève ModelSyntaxError si la forme ne tient pas."""
    if fmt not in FORMATS:
        raise ValueError(f"format inconnu : {fmt!r}")
    if fmt == YAML_FORMAT:
        # Le chargeur strict du projet : mêmes limites de taille et mêmes refus qu'ailleurs.
        return load_yaml(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Les lignes et colonnes de json sont 1-indexées comme celles de YAML : l'écran
        # peut pointer l'endroit sans retraduire.
        raise ModelSyntaxError(exc.msg, exc.lineno, exc.colno) from None


class SampleNotAnObjectError(ValueError):
    """L'échantillon ne décrit pas un objet, et un modèle Miles en décrit toujours un."""


def infer_root(sample: Any) -> tuple[dict[str, Any], bool]:
    """Le schéma du modèle, et si on a dû dégager l'échantillon de son enveloppe.

    La grammaire exige `type: object` à la racine (schema.py, « objet_attendu »). Or on
    colle le plus souvent une LISTE d'exemplaires — un export, un extrait de flux. Cette
    liste est l'enveloppe de l'échantillon, pas le modèle : on décrit donc un de ses
    éléments, tous fusionnés. Sans cela l'import produisait un `type: array` que Miles
    refusait aussitôt — le modèle était fabriqué pour être rejeté (constaté le
    24/10/2026 sur un export de points relais).
    """
    if isinstance(sample, list):
        if not sample:
            raise SampleNotAnObjectError("échantillon vide")
        schema = _merged([infer(item) for item in sample])
        if schema.get("type") != "object":
            raise SampleNotAnObjectError("les éléments ne sont pas des objets")
        return schema, True
    schema = infer(sample)
    if schema.get("type") != "object":
        raise SampleNotAnObjectError("l'échantillon n'est pas un objet")
    return schema, False


def infer(sample: Any) -> dict[str, Any]:
    """Le schéma que cet échantillon prouve — rien de plus."""
    if isinstance(sample, dict):
        properties = {str(key): infer(value) for key, value in sample.items()}
        # Pas de `required` : voir le parti pris en tête de module.
        return {"type": "object", "properties": properties}
    if isinstance(sample, list):
        if not sample:
            # Une liste vide ne dit rien de ses éléments : on ne l'invente pas.
            return {"type": "array"}
        items = _merged([infer(item) for item in sample])
        return {"type": "array", "items": items}
    return _scalar(sample)


def _scalar(value: Any) -> dict[str, Any]:
    # bool AVANT int : en Python, True est un int, et un booléen deviendrait un entier.
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, str):
        for name, pattern in _FORMATS:
            if pattern.match(value):
                return {"type": "string", "format": name}
        return {"type": "string"}
    # Date ou autre objet rendu par le chargeur YAML : on le dit chaîne plutôt que de
    # laisser passer un type que JSON Schema ne connaît pas.
    return {"type": "string"}


def _merged(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """Fond les schémas des éléments d'un tableau en un seul.

    Fusionner TOUS les éléments, et pas seulement le premier : un tableau dont le second
    élément porte une clé de plus produirait sinon un schéma qui le refuse.
    """
    merged = schemas[0]
    for other in schemas[1:]:
        merged = _merge(merged, other)
    return merged


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left == right:
        return left
    if left.get("type") == "object" and right.get("type") == "object":
        keys = list(left.get("properties", {})) + [
            k for k in right.get("properties", {}) if k not in left.get("properties", {})
        ]
        properties = {}
        for key in keys:
            here, there = left.get("properties", {}).get(key), right.get("properties", {}).get(key)
            if here is None or there is None:
                # Clé vue d'un seul côté : on garde ce qu'on en sait, sans l'exiger —
                # `required` étant vide, rien ne la rend obligatoire.
                properties[key] = here if there is None else there
            else:
                properties[key] = _merge(here, there)
        return {"type": "object", "properties": properties}
    if left.get("type") == "array" and right.get("type") == "array":
        here, there = left.get("items"), right.get("items")
        if here is None or there is None:
            return {"type": "array", **({"items": here or there} if (here or there) else {})}
        return {"type": "array", "items": _merge(here, there)}
    # Types qui ne se rejoignent pas : on les énumère plutôt que d'en choisir un. Le
    # `format` tombe, puisqu'il ne vaut que pour l'un d'eux.
    kinds = _types(left) + [t for t in _types(right) if t not in _types(left)]
    # Un seul type restant (deux chaînes de formats différents) : on l'écrit tel quel,
    # une liste d'un élément étant valide mais pénible à relire.
    return {"type": kinds[0] if len(kinds) == 1 else kinds}


def _types(schema: dict[str, Any]) -> list[str]:
    kind = schema.get("type")
    if isinstance(kind, list):
        return [str(k) for k in kind]
    return [str(kind)] if kind is not None else []
