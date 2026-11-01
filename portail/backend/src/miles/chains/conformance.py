"""Ce que le template ÉCRIT, confronté au modèle de destination que l'étape annonce.

Demandé par Gael le 01/11/2026 : « un flag d'alerte sur les steps de transformations
quand le model à l'enregistrement n'est pas valide avec le model cible choisi ». Et,
précisé par lui le même jour : on juge le TEXTE du template, sans l'exécuter. Le verdict
vaut alors pour toutes les données, et non pour le seul échantillon de test — au prix de
ne rien pouvoir dire des types, qui dépendent du contenu.

Une alerte, jamais un refus : la chaîne s'enregistre. Ce qui ne peut pas s'exécuter est
déjà refusé par le profil d'écriture ; ici on parle d'une INTENTION déclarée, que son
auteur est peut-être en train d'écrire.

On ne signale que ce qui est CERTAIN depuis le texte : la descente suit les objets et
les tableaux LITTÉRAUX, et s'arrête devant un chemin, une constante, un appel de
fonction ou un `switch`. Une alerte fausse se fait ignorer, puis fait ignorer les vraies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from urban_json.ast import JsltBase
from urban_json.ast.nodes import JsltArray, JsltObject

from miles.datamodels.example import MAX_DEPTH
from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import model_path
from miles.datamodels.navigate import Read, kind_of, resolved
from miles.datamodels.paths import ROOT
from miles.datamodels.schema import target_of
from miles.transform.engine import TemplateSyntaxError, UnsupportedConstructError, parse_ast


@dataclass(frozen=True)
class Divergence:
    """Un écart certain entre ce que le template écrit et le modèle qu'il annonce."""

    # Chemin DANS LE RÉSULTAT, pas dans le template : c'est ce que l'auteur regarde.
    path: str
    code: str
    detail: str | None = None


def ast_of(template: str) -> JsltBase | None:
    """L'arbre du template, ou None s'il ne se lit pas.

    Illisible, il est déjà refusé à l'écriture et signalé par la validation de la
    branche : en reparler ici ferait deux messages pour un seul défaut.
    """
    try:
        return parse_ast(template)
    except (TemplateSyntaxError, UnsupportedConstructError):
        return None


async def divergences(
    read: Read, model: str | None, ast: JsltBase | None
) -> tuple[Divergence, ...]:
    """Les écarts entre ce que le template écrit et ce que `model` déclare.

    Aucun écart quand l'étape n'annonce pas de modèle, ou quand le modèle est
    introuvable ou illisible : une absence de déclaration n'est pas une contradiction.
    C'est la règle que Gael a posée le 25/10/2026 pour les extrémités d'une chaîne, et
    la tenir ici aussi évite qu'une chaîne écrite avant les modèles d'étape se couvre
    d'alertes du jour au lendemain.
    """
    if model is None or ast is None:
        return ()
    target = target_of(model)
    if target is None:
        return ()
    text = await read(model_path(*target))
    if text is None:
        return ()
    try:
        root = load_yaml(text)
    except ValueError:
        return ()
    found: list[Divergence] = []
    await _check(read, target[0], root, root, ast, ROOT, found, 0)
    return tuple(found)


async def _check(
    read: Read,
    scope: str,
    root: Any,
    schema: Any,
    node: JsltBase,
    path: str,
    found: list[Divergence],
    depth: int,
) -> None:
    # Borne de descente : un modèle qui se référence lui-même (noeud → parent: noeud)
    # tournerait sans fin. On s'arrête en silence plutôt que de déborder la pile.
    if depth > MAX_DEPTH:
        return
    seen = await resolved(read, schema, root, scope)
    if seen is None or not isinstance(seen[0], dict):
        return
    schema, root, scope = seen
    if isinstance(node, JsltObject):
        await _object(read, scope, root, schema, node, path, found, depth)
    elif isinstance(node, JsltArray):
        await _array(read, scope, root, schema, node, path, found, depth)


async def _object(
    read: Read,
    scope: str,
    root: Any,
    schema: dict[str, Any],
    node: JsltObject,
    path: str,
    found: list[Divergence],
    depth: int,
) -> None:
    kind = kind_of(schema)
    if kind is not None and kind != "object":
        found.append(Divergence(path, "objet_inattendu", kind))
        return
    declared = schema.get("properties")
    if not isinstance(declared, dict):
        # Le modèle ne décrit pas ce qu'il y a ici : on ne sait rien, on se tait.
        return
    # `properties` du nœud laisse de côté `$source`, `$where` et `$type`, que l'arbre
    # range ailleurs : ce sont des directives, pas des propriétés du résultat.
    written = {p.name: p for p in node.properties if isinstance(p.name, str)}
    found += [
        Divergence(_join(path, name), "propriete_hors_modele")
        for name in written
        if name not in declared
    ]
    required = schema.get("required")
    if isinstance(required, list):
        found += [
            Divergence(_join(path, name), "propriete_obligatoire_absente")
            for name in required
            if isinstance(name, str) and name not in written
        ]
    for name, prop in written.items():
        sub = declared.get(name)
        if isinstance(sub, dict) and prop.value is not None:
            await _check(read, scope, root, sub, prop.value, _join(path, name), found, depth + 1)


async def _array(
    read: Read,
    scope: str,
    root: Any,
    schema: dict[str, Any],
    node: JsltArray,
    path: str,
    found: list[Divergence],
    depth: int,
) -> None:
    kind = kind_of(schema)
    if kind is not None and kind != "array":
        found.append(Divergence(path, "tableau_inattendu", kind))
        return
    items = schema.get("items")
    if not isinstance(items, dict):
        return
    # Chaque élément écrit est confronté à `items` : un élément porteur d'un `$source`
    # est une boucle, mais tous ses tours ont la forme de cet élément — la vérifier une
    # fois suffit, et la vérifier par tour dirait la même chose plusieurs fois.
    for index, item in enumerate(node.items):
        await _check(read, scope, root, items, item, f"{path}[{index}]", found, depth + 1)


def _join(path: str, key: str) -> str:
    # Même citation que les chemins proposés à l'éditeur : un « . » ou un « [ » dans un
    # nom de propriété casserait le chemin rendu.
    return f"{path}.{key}" if key.isidentifier() else f'{path}["{key}"]'
