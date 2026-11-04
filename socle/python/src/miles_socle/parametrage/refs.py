"""Remplacer les renvois d'un modèle vers d'autres modèles par leur contenu.

Un modèle qui en désigne un autre (`$ref: miles:/domains/pudo/adresse`) n'offrirait sinon
aucun chemin sous ce renvoi : ni dans l'arbre des propriétés du portail, ni dans le
typage des colonnes de l'environnement. Les deux doivent voir le MÊME schéma — sans quoi
l'écran proposerait une colonne que l'environnement refuserait ensuite.

Extrait du module de paramétrage le 02/11/2026, deuxième usage. La lecture est passée en
paramètre : ce module ne sait pas si elle vient d'une copie de travail git, d'un arbre
servi ou d'un dictionnaire d'essai, et il n'a pas à le savoir.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from miles_socle.parametrage.layout import model_path, target_of
from miles_socle.parametrage.yaml_read import load_yaml

# Profondeur de modèles désignés : un cycle entre deux modèles est déjà arrêté par
# `seen`, mais une chaîne longue n'a pas non plus d'intérêt dans un gabarit.
MAX_MODEL_DEPTH = 8

ReadFile = Callable[[str], Awaitable[str | None]]


async def inline_refs(read: ReadFile, schema: Any, origin: tuple[str, str]) -> Any:
    """Le schéma, renvois vers d'autres modèles remplacés par leur contenu."""
    return await _inlined(read, schema, {origin}, 0)


async def _inlined(read: ReadFile, node: Any, seen: set[tuple[str, str]], depth: int) -> Any:
    """Remplace les `$ref` vers d'autres modèles par leur schéma, en place.

    Les `#/…` ne sont pas touchés : celui qui exploite le schéma les suit tout seul dans
    le document. Un modèle déjà traversé n'est pas rouvert — deux modèles qui se
    désignent l'un l'autre boucleraient sans fin.
    """
    if isinstance(node, list):
        return [await _inlined(read, item, seen, depth) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and (target := target_of(ref)) is not None:
        if target in seen or depth >= MAX_MODEL_DEPTH:
            # Laissé tel quel : l'exploitant rendra une place vide, ce qui se voit,
            # plutôt qu'une descente sans fin.
            return node
        content = await read(model_path(*target))
        if content is None:
            return node
        return await _inlined(read, load_yaml(content), seen | {target}, depth + 1)
    return {key: await _inlined(read, value, seen, depth) for key, value in node.items()}
