from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import model_path
from miles.datamodels.schema import target_of

Read = Callable[[str], Awaitable[str | None]]
# Borne de la résolution des `$ref` : un modèle qui se désigne lui-même (personne →
# parent: personne) ferait boucler la descente sans elle.
MAX_HOPS = 16


def _sees(scope: str, target_scope: str) -> bool:
    return target_scope == "shared" or (scope != "shared" and target_scope == scope)


def _pointer(root: Any, ref: str) -> Any:
    node = root
    for part in ref.removeprefix("#").strip("/").split("/"):
        if not part:
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        node = node.get(part) if isinstance(node, dict) else None
    return node


async def _resolved(read: Read, node: Any, root: Any, scope: str) -> tuple[Any, Any, str] | None:
    """Suit les `$ref` (internes ou vers un modèle visible) jusqu'au schéma qu'ils désignent."""
    for _ in range(MAX_HOPS):
        ref = node.get("$ref") if isinstance(node, dict) else None
        if not isinstance(ref, str):
            return node, root, scope
        if ref.startswith("#"):
            node = _pointer(root, ref)
            continue
        target = target_of(ref)
        if target is None or not _sees(scope, target[0]):
            return None
        text = await read(model_path(*target))
        if text is None:
            return None
        try:
            root = load_yaml(text)
        except ValueError:
            return None
        scope, node = target[0], _pointer(root, ref.split("#", 1)[1]) if "#" in ref else root
    return None


def _kind(node: Any) -> str | None:
    kind = node.get("type") if isinstance(node, dict) else None
    if isinstance(kind, list):
        # `[string, "null"]` : une valeur facultative reste de son type.
        others = [k for k in kind if k != "null"]
        kind = others[0] if len(others) == 1 else None
    if kind is None and isinstance(node, dict) and "properties" in node:
        return "object"
    return kind if isinstance(kind, str) else None


async def kind_at(read: Read, scope: str, root: Any, keys: list[str]) -> str | None:
    """Le type JSON Schema de la propriété au bout de `keys`, en traversant objets et `$ref`."""
    node: Any = root
    for key in keys:
        found = await _resolved(read, node, root, scope)
        if found is None:
            return None
        node, root, scope = found
        child = (node.get("properties") or {}).get(key) if isinstance(node, dict) else None
        if not isinstance(child, dict):
            return None
        node = child
    found = await _resolved(read, node, root, scope)
    return None if found is None else _kind(found[0])
