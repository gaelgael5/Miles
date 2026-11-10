"""Chemins d'un modèle de données, et le type que le schéma garantit à chacun.

Écrit pour l'intellisense de l'éditeur JSLT (Gael, 24/10/2026) : le composant
`<jslt-editor>` complète les chemins du document source quand on tape `$` ou `@`, et ne
lit aucun JSON Schema — c'est l'hôte qui calcule la liste.

Les tableaux sont rendus **indexés** (`$.Account[0].Name`) et non en `[*]` : c'est la
forme qu'on écrit réellement dans un template, et le composant ne propose jamais un index
qu'on ne lui a pas donné. Un seul index suffit — proposer `[1]`, `[2]`… n'apprendrait
rien de plus sur la forme.

**Extrait au socle le 02/11/2026**, deuxième usage : le module d'environnement type les
colonnes projetées de ses tables, et il doit les typer comme le modèle le dit — donc avec
le MÊME vocabulaire que celui montré à qui a choisi la colonne dans l'arbre. Deux
lecteurs de schéma auraient fini par nommer le même type autrement, et la colonne aurait
cessé de correspondre à ce que l'écran promettait.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Un modèle large produirait des milliers de chemins, que personne ne parcourt. La liste
# est bornée : au-delà, l'auto-complétion dessert plus qu'elle ne sert.
MAX_PATHS = 2000
# Profondeur de descente ; un schéma récursif par `$ref` ne doit pas faire tourner la
# marche indéfiniment.
MAX_DEPTH = 12
ROOT = "$"


@dataclass(frozen=True)
class PathEntry:
    path: str
    # Type JSON Schema du nœud ; « valeur » quand le schéma ne le dit pas.
    kind: str
    # `title` du schéma, pour que la proposition se lise. Vide s'il n'en porte pas.
    description: str
    # Les noms de propriétés traversés depuis la racine, ou None dès qu'un indice de
    # tableau a été franchi. None dit « ce chemin ne désigne pas une propriété d'objet » :
    # c'est ce qui interdit d'en faire une colonne projetée, puisqu'il n'existe aucun
    # chemin jsonb scalaire qui y mène.
    keys: tuple[str, ...] | None = None
    # Le `format` du schéma (« date-time », « uri », « email »…), vide quand il n'en
    # porte pas. À CÔTÉ de `kind` et jamais fondu dedans : `kind` décide AUSSI du type
    # SQL d'une colonne projetée (`sql_type_of` du module d'environnement), et l'enrichir
    # ferait porter au même champ deux rôles qui n'ont pas à bouger ensemble.
    # Relevé par Gael le 10/11/2026 : l'arbre des propriétés annonçait « string » là où
    # l'éditeur de modèle montrait « Date-Heure », parce que la marche ne lisait que
    # `type` — l'information n'était pas perdue en route, elle n'était jamais lue.
    format: str = ""


def paths_of(schema: Any) -> list[PathEntry]:
    """Les chemins que ce schéma décrit, du plus proche de la racine au plus profond."""
    found: list[PathEntry] = []
    _walk(schema, schema, ROOT, (), found, 0)
    return found[:MAX_PATHS]


def _walk(
    node: Any,
    root: Any,
    path: str,
    keys: tuple[str, ...] | None,
    found: list[PathEntry],
    depth: int,
) -> None:
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
            below = None if keys is None else (*keys, str(key))
            resolved = _resolved(sub, root) or {}
            found.append(
                PathEntry(step, _kind(resolved), _title(resolved), below, _format(resolved))
            )
            _walk(sub, root, step, below, found, depth + 1)
        return
    items = node.get("items")
    if isinstance(items, dict):
        # Un seul index : le composant ne propose que ce qu'on lui donne, et « [1] »
        # n'apprendrait rien de plus sur la forme.
        step = f"{path}[0]"
        resolved = _resolved(items, root) or {}
        found.append(PathEntry(step, _kind(resolved), _title(resolved), None, _format(resolved)))
        _walk(items, root, step, None, found, depth + 1)


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


def _format(schema: dict[str, Any]) -> str:
    """Le `format` du schéma, rendu tel qu'il est écrit.

    Non interprété : JSON Schema laisse le vocabulaire ouvert, et traduire ici « date-time »
    en un mot choisi par nous ferait diverger ce que l'arbre annonce de ce que le schéma dit.
    """
    kind = schema.get("format")
    return kind if isinstance(kind, str) else ""


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


# L'utilité des champs, écrite par le portail à la RACINE du modèle (Gael, 05/11/2026) :
# quels champs identifient un objet, et lesquels se montrent en colonne. Le nom du mot-clé
# est au socle parce qu'il est un CONTRAT entre deux modules — le portail l'écrit, le
# module d'environnement le lit —, et deux constantes de même valeur dans deux produits
# auraient divergé au premier renommage fait d'un seul côté : la déclaration serait alors
# ignorée sans que rien ne soit faux de part ni d'autre.
USAGE_KEYWORD = "x-miles"


@dataclass(frozen=True)
class ModelUsage:
    """Ce que le modèle déclare de ses champs, par jpath (`$.Id`), dans son ordre."""

    key: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()


def _declared_paths(value: Any) -> tuple[str, ...]:
    # Le fichier s'édite aussi à la main, et hors de Miles : ce qui n'est pas une liste
    # de chemins est ignoré, plutôt que de faire échouer la lecture de la version.
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def usage_of(schema: Any) -> ModelUsage:
    """L'utilité déclarée par ce modèle ; vide quand il n'en déclare aucune."""
    if not isinstance(schema, dict):
        return ModelUsage()
    declared = schema.get(USAGE_KEYWORD)
    if not isinstance(declared, dict):
        return ModelUsage()
    return ModelUsage(
        key=_declared_paths(declared.get("key")),
        columns=_declared_paths(declared.get("columns")),
    )
