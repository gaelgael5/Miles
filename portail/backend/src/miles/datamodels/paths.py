"""Chemins d'un modèle, pour l'intellisense de l'éditeur JSLT (Gael, 24/10/2026).

L'éditeur `<jslt-editor>` (urban-json-editor ≥ 0.2.0) complète les chemins du document
source quand on tape `$` ou `@`. Il ne lit aucun JSON Schema : c'est l'hôte qui calcule
la liste, et c'est ce que fait ce module.

Les tableaux sont rendus **indexés** (`$.Account[0].Name`) et non en `[*]` : c'est la
forme qu'on écrit réellement dans un template, et le composant ne propose jamais un index
qu'on ne lui a pas donné. Un seul index suffit — proposer `[1]`, `[2]`… n'apprendrait
rien de plus sur la forme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from miles.datamodels.example import MAX_DEPTH

# Un modèle large produirait des milliers de chemins, que personne ne parcourt. La liste
# est bornée : au-delà, l'auto-complétion dessert plus qu'elle ne sert.
MAX_PATHS = 2000
ROOT = "$"


@dataclass(frozen=True)
class PathEntry:
    path: str
    # Type JSON Schema du nœud ; « valeur » quand le schéma ne le dit pas.
    kind: str
    # `title` du schéma, pour que la proposition se lise. Vide s'il n'en porte pas.
    description: str


def paths_of(schema: Any) -> list[PathEntry]:
    """Les chemins que ce schéma décrit, du plus proche de la racine au plus profond."""
    found: list[PathEntry] = []
    _walk(schema, schema, ROOT, found, 0)
    return found[:MAX_PATHS]


def _walk(node: Any, root: Any, path: str, found: list[PathEntry], depth: int) -> None:
    if depth > MAX_DEPTH or len(found) >= MAX_PATHS or not isinstance(node, dict):
        return
    node = _resolved(node, root)
    if node is None:
        return
    properties = node.get("properties")
    if isinstance(properties, dict):
        for key, sub in properties.items():
            # `.` et `[` dans un nom de propriété casseraient le chemin : on le cite,
            # comme le fait n'importe quel sélecteur sur une clé exotique.
            step = f"{path}.{key}" if _plain(str(key)) else f'{path}["{key}"]'
            resolved = _resolved(sub, root) or {}
            found.append(PathEntry(step, _kind(resolved), _title(resolved)))
            _walk(sub, root, step, found, depth + 1)
        return
    items = node.get("items")
    if isinstance(items, dict):
        # Un seul index : le composant ne propose que ce qu'on lui donne, et « [1] »
        # n'apprendrait rien de plus sur la forme.
        step = f"{path}[0]"
        resolved = _resolved(items, root) or {}
        found.append(PathEntry(step, _kind(resolved), _title(resolved)))
        _walk(items, root, step, found, depth + 1)


def _plain(key: str) -> bool:
    return key.isidentifier()


def _kind(schema: dict[str, Any]) -> str:
    kind = schema.get("type")
    if isinstance(kind, list):
        return "|".join(str(k) for k in kind) or "valeur"
    # Sans `type`, des propriétés font tout de même un objet ; sinon on ne sait pas.
    if kind is None:
        return "object" if isinstance(schema.get("properties"), dict) else "valeur"
    return str(kind)


def _title(schema: dict[str, Any]) -> str:
    title = schema.get("title")
    return str(title) if isinstance(title, str) else ""


def _resolved(schema: dict[str, Any], root: Any) -> dict[str, Any] | None:
    """Suit un `$ref` interne (`#/…`) ; les renvois vers un autre modèle sont résolus
    en amont par le service, qui seul sait lire la branche."""
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None
