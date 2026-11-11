"""Modifier UNE propriété d'un schéma, sans réécrire le document.

Pourquoi (Gael, 11/11/2026) : un agent qui ajoute un champ devait renvoyer le schéma
ENTIER. Plus le modèle est riche, plus l'artefact est gros, et plus il y a d'occasions de
perdre en route ce qu'il n'avait pas l'intention de toucher — un `$defs`, un `x-miles`,
une propriété oubliée. Une primitive qui ne porte que la propriété visée rend l'artefact
petit, et ce qu'elle ne nomme pas ne peut pas disparaître.

Ce module ne fait QUE la mutation du document, et il est pur : il ne lit ni n'écrit rien.
La validation et l'écriture restent celles des deux familles (modèles, événements), de
sorte qu'un document modifié par une propriété reçoive exactement les mêmes écarts qu'un
document remplacé en entier.

Il sert les DEUX familles, et c'est voulu : un événement est un JSON Schema écrit en YAML
comme un modèle, et une seconde marche sur les mêmes mots aurait divergé au premier
ajustement.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import yaml

from miles.datamodels.grammar import load_yaml

#: Segment qui descend dans les éléments d'un tableau. Choisi parce qu'il ne peut pas
#: être un nom de propriété JSON Schema ambigu dans un chemin : un nom de propriété peut
#: contenir un point, ce qui interdit un chemin pointé, mais pas des crochets vides.
ARRAY = "[]"


class PropertyPathError(ValueError):
    """Le chemin ne désigne pas un endroit où une propriété peut vivre.

    Porte `code`, l'endroit atteint (`where`, le chemin parcouru) et ce qui EXISTE là
    (`existing`) : sans cette liste, un agent qui s'est trompé d'un nom réessaie à
    l'aveugle, et c'est exactement le comportement que la surface MCP cherche à éviter.
    """

    def __init__(self, code: str, where: list[str], existing: list[str]) -> None:
        super().__init__(f"{code} à « {'.'.join(where) or '<racine>'} »")
        self.code = code
        self.where = list(where)
        self.existing = list(existing)


def _names(node: Any) -> list[str]:
    properties = node.get("properties") if isinstance(node, dict) else None
    return sorted(properties) if isinstance(properties, dict) else []


def _descend(node: Any, segment: str, walked: list[str]) -> Any:
    """Le nœud sous `segment`, ou une erreur qui dit POURQUOI on ne peut pas y aller."""
    if not isinstance(node, dict):
        raise PropertyPathError("chemin_sans_proprietes", walked, [])
    # Un `$ref` ne se traverse PAS : le schéma désigné vit dans un autre document, et
    # l'y modifier à travers ce chemin écrirait dans un fichier que l'appel ne nomme pas.
    # L'agent doit ouvrir le modèle désigné — le refus le lui dit en le nommant.
    if isinstance(node.get("$ref"), str):
        raise PropertyPathError("renvoi_traverse", walked, [str(node["$ref"])])
    if segment == ARRAY:
        items = node.get("items")
        if not isinstance(items, dict):
            raise PropertyPathError("tableau_sans_items", walked, [])
        return items
    properties = node.get("properties")
    child = properties.get(segment) if isinstance(properties, dict) else None
    if child is None:
        raise PropertyPathError("propriete_inconnue", [*walked, segment], _names(node))
    return child


def _parent(document: dict[str, Any], path: list[str]) -> tuple[Any, str, list[str]]:
    """Le nœud qui PORTERA la propriété, le nom de celle-ci, et le chemin parcouru."""
    if not path:
        raise PropertyPathError("chemin_vide", [], _names(document))
    *tete, nom = path
    if nom == ARRAY:
        # `[]` ne nomme rien : une propriété a un nom, et un tableau n'en porte pas.
        raise PropertyPathError("nom_de_propriete_attendu", path, [])
    node: Any = document
    walked: list[str] = []
    for segment in tete:
        node = _descend(node, segment, walked)
        walked.append(segment)
    return node, nom, walked


def set_property(
    document: dict[str, Any], path: list[str], schema: Any, *, required: bool | None = None
) -> dict[str, Any]:
    """Pose ou remplace la propriété au bout de `path` ; rend un NOUVEAU document.

    `required` : `True` l'ajoute aux propriétés obligatoires du nœud qui la porte, `False`
    l'en retire, et OMIS ne touche pas à la liste. Omis n'est donc pas « facultative » :
    c'est « laisse comme c'était », pour qu'un agent qui corrige un type ne dégrade pas
    une obligation qu'il n'a pas nommée. Une propriété neuve, elle, naît facultative —
    c'est l'état par défaut de JSON Schema, pas une déduction de ce module.
    """
    patched = copy.deepcopy(document)
    node, nom, _ = _parent(patched, path)
    if not isinstance(node, dict):
        raise PropertyPathError("chemin_sans_proprietes", path[:-1], [])
    if isinstance(node.get("$ref"), str):
        raise PropertyPathError("renvoi_traverse", path[:-1], [str(node["$ref"])])
    properties = node.get("properties")
    if not isinstance(properties, dict):
        # Un objet déclaré sans `properties` en reçoit une : c'est le cas d'un modèle
        # qu'on vient de déclarer, dont le schéma est `{type: object, properties: {}}`.
        properties = {}
        node["properties"] = properties
    properties[nom] = copy.deepcopy(schema)
    _require(node, nom, required)
    return patched


def remove_property(document: dict[str, Any], path: list[str]) -> dict[str, Any]:
    """Retire la propriété au bout de `path`, et son obligation ; rend un NOUVEAU document.

    Retirer la propriété SANS la retirer de `required` laisserait un schéma qu'aucun
    document ne peut satisfaire : la liste exigerait un champ que le schéma ne décrit
    plus. Les deux gestes n'en font donc qu'un.
    """
    patched = copy.deepcopy(document)
    node, nom, walked = _parent(patched, path)
    properties = node.get("properties") if isinstance(node, dict) else None
    if not isinstance(properties, dict) or nom not in properties:
        raise PropertyPathError("propriete_inconnue", [*walked, nom], _names(node))
    del properties[nom]
    _require(node, nom, False)
    return patched


def _require(node: dict[str, Any], nom: str, required: bool | None) -> None:
    if required is None:
        return
    current = node.get("required")
    names = [n for n in current if isinstance(n, str)] if isinstance(current, list) else []
    if required and nom not in names:
        names.append(nom)
    if not required:
        names = [n for n in names if n != nom]
    if names:
        node["required"] = names
    elif "required" in node:
        # Une liste vide est admise par le méta-schéma mais ne dit rien : on retire la
        # clef plutôt que de laisser `required: []` dans le fichier.
        del node["required"]


def patched(text: str, apply: Callable[[dict[str, Any]], dict[str, Any]]) -> str:
    """Le document lu, muté, et réécrit en YAML — prêt pour la validation habituelle.

    Le refus d'un document qui n'est pas un objet est rendu ICI comme une erreur de
    CHEMIN et non de grammaire, et c'est voulu : il vaut pour les deux familles, et le
    nom du refus ne doit pas dépendre de celle qu'on modifie.
    """
    document = load_yaml(text)
    if not isinstance(document, dict):
        raise PropertyPathError("document_non_objet", [], [])
    return yaml.safe_dump(apply(document), allow_unicode=True, sort_keys=False)
