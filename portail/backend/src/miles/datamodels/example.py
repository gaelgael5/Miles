"""Gabarit JSON déduit d'un schéma de modèle (Gael, 24/10/2026).

Sert le bouton « remplir depuis le modèle de destination » de l'éditeur de template : on
part de la forme que le modèle décrit, plutôt que de la retaper à la main.

Ce que porte le gabarit, demandé par Gael le 24/10/2026 : une chaîne porte **le nom de sa
propriété**, un nombre vaut 0, un booléen `false`, et objets comme tableaux sont remplis
de leur forme. Un tableau porte **toujours au moins un élément** : un tableau vide ne
montrerait pas ce qu'il contient, et c'est justement ce qu'on vient chercher.

Le gabarit montre la STRUCTURE. Rien n'y ressemble à une vraie donnée, et c'est voulu :
un exemple réaliste finirait recopié en production.
"""

from __future__ import annotations

from typing import Any

# Profondeur maximale : un modèle qui se référence lui-même (`#/$defs/noeud` dans
# `noeud`) ferait sinon une descente sans fin. On s'arrête en laissant la place vide
# plutôt que de déborder la pile.
MAX_DEPTH = 12


def example_of(schema: Any, root: Any = None, name: str = "", depth: int = 0) -> Any:
    """Le gabarit de ce schéma. `root` sert à résoudre les `$ref` internes (`#/…`)."""
    if depth > MAX_DEPTH or not isinstance(schema, dict):
        return None
    if root is None:
        root = schema
    resolved = _resolved(schema, root)
    if resolved is None:
        # `$ref` qu'on ne sait pas suivre — vers un AUTRE modèle (miles:/…), que le
        # service résout avant d'appeler ici. Parvenu jusqu'ici, il reste non résolu :
        # on laisse la place vide plutôt que d'inventer une forme.
        return None
    schema = resolved
    kind = _kind(schema)
    if kind == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        return {key: example_of(sub, root, str(key), depth + 1) for key, sub in properties.items()}
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            # Sans description des éléments, un élément inventé mentirait sur leur forme.
            return []
        # Le nom porté est celui de la propriété qui tient le tableau : une liste de
        # chaînes « Tags » donne ["Tags"], ce qui dit d'où vient la valeur.
        return [example_of(items, root, name, depth + 1)]
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        return 0
    if kind == "null":
        return None
    # Chaîne, ou type absent : le nom de la propriété. Au niveau racine il n'y en a pas,
    # et la chaîne vide est alors la seule valeur honnête.
    return name


def _kind(schema: dict[str, Any]) -> str | None:
    """Le type retenu ; d'une union, le premier qui n'est pas « null ».

    « null » en premier d'une union décrirait un gabarit vide là où le modèle accepte
    autre chose : on montre la forme utile, pas l'absence.
    """
    kind = schema.get("type")
    if isinstance(kind, list):
        useful = [k for k in kind if k != "null"]
        return str(useful[0]) if useful else "null"
    if kind is None:
        # Pas de `type`, mais des propriétés : c'est un objet, et le dire sert mieux que
        # de rendre une chaîne.
        return "object" if isinstance(schema.get("properties"), dict) else None
    return str(kind)


def _resolved(schema: dict[str, Any], root: Any) -> dict[str, Any] | None:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        # Les pointeurs JSON échappent « / » et « ~ » ; on les rétablit avant de descendre.
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None
