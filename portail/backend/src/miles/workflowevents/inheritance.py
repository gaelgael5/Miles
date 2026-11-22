"""L'héritage entre types d'event : un `allOf: $ref` dans le modèle du payload.

Décidé le 22/11/2026 (feature `c8f3d8da`, décision 1, story `6064ce93`) : l'héritage n'est
pas un dispositif de Miles, c'est la **composition** de JSON Schema. Le standard n'a aucun
mot-clé d'héritage — `extends` existait en draft-03 et a été retiré —, et « pointer un
autre document » s'écrit `$ref`. Donc rien n'est recopié du parent, et aucun fichier de
métadonnées ne porte le lien de parenté : **le lien EST le `$ref`**, et rediriger
l'héritage réécrit cette seule ligne.

Le `$ref` porte l'`$id` du modèle parent (`miles:/shared/colis`), la forme que le dépôt
écrit depuis le 23/10/2026 : `model_id` le pose, `workshop.validation` vérifie qu'il
correspond à l'emplacement du fichier, et `datamodels.links.check_references` vérifie que
la cible existe et est visible. Il est TOUJOURS absolu — mesuré le 22/11/2026 : sous le
schéma d'URI `miles:`, un `$ref` relatif ne résout pas, `urllib.parse.urljoin` ne faisant
pas de résolution relative sur un schéma d'URI inconnu.

Module PUR, qui prend un lecteur et jamais la copie de travail : il s'éprouve sans dépôt
ni forge (leçon du 17/11/2026, qui a coûté dix tests de campagne pour un défaut d'une
ligne).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml
from miles.datamodels.layout import model_path
from miles.datamodels.schema import model_id, parse_schema, target_of
from miles.workflowevents.schema import payload_problems

# Lire UN fichier de la branche, ou None s'il n'y est pas — le contrat de
# `workflowevents.reading` et de `datamodels.usages`.
Reader = Callable[[str], Awaitable[str | None]]

# Borne de la remontée des parents. Même valeur et même raison que
# `datamodels.navigate.MAX_HOPS`, qui borne la descente des `$ref`. Et ce n'est pas une
# précaution : mesuré le 22/11/2026, `jsonschema` part en `RecursionError` sur un schéma
# qui se `$ref` — sans refus au geste, le portail rendrait 500 et le moteur tomberait.
MAX_DEPTH = 16

RECURSIVE = "heritage_recursif"
TOO_DEEP = "heritage_trop_profond"


def parents_of(text: str) -> tuple[tuple[str, str], ...]:
    """Les modèles dont ce payload hérite : les `$ref` de son `allOf` de tête.

    Tolérant à dessein, comme `references_in` : un fichier retouché hors de Miles doit
    encore dire de quoi il hérite — c'est ce que l'écran affiche, et c'est sur quoi porte
    le refus des cycles. Un document illisible n'hérite de rien, et la validation de la
    branche dira pourquoi.

    Seul l'`allOf` de TÊTE compte : un `$ref` posé sous une propriété désigne le type de
    cette propriété, pas un parent. C'est la distinction que fait le standard entre
    composer un schéma et typer un champ.
    """
    try:
        data = load_yaml(text)
    except ValueError:
        return ()
    return tuple(target for _, target in _inherited(data))


def with_parent(text: str, parent: tuple[str, str] | None) -> str:
    """Le même modèle, dont l'héritage désigne `parent` — ou n'en désigne plus aucun.

    `None` rend un modèle qui ne tient que du socle commun : c'est l'event de base, et il
    n'a aucun `$ref` à écrire parce que le moteur applique sa racine d'office
    (`SchemaRegistry.validate`, `include_base`). Décision 2 du 22/11/2026.

    Ce qui n'est pas un héritage dans l'`allOf` est CONSERVÉ — un `allOf` écrit à la main
    peut porter une contrainte qui ne désigne aucun modèle, et la perdre au passage
    changerait le sens du document sans que personne ne l'ait demandé.
    """
    data = load_yaml(text)
    if not isinstance(data, dict):
        raise ModelGrammarError([Problem("", "document_non_objet")])
    herites = {rang for rang, _ in _inherited(data)}
    gardes = [item for index, item in enumerate(_all_of(data)) if index not in herites]
    entries = ([{"$ref": model_id(*parent)}] if parent is not None else []) + gardes
    return yaml.safe_dump(_with_all_of(data, entries), allow_unicode=True, sort_keys=False)


async def ancestors(
    read: Reader, parents: Sequence[tuple[str, str]]
) -> tuple[tuple[str, str], ...] | None:
    """Les modèles au-dessus de `parents`, ceux-ci inclus. `None` : plus profond que la borne.

    Parcours en largeur sur TOUS les parents d'un `allOf`, et non sur le premier : ne
    suivre que l'un d'eux laisserait passer un cycle par l'autre. Un modèle déjà vu n'est
    pas revisité, donc un cycle ne fait pas boucler ce parcours — il se reconnaît à ce que
    l'enfant se retrouve dans la liste rendue, et c'est `cycle_problems` qui le dit.
    """
    seen = list(dict.fromkeys(parents))
    frontier = list(seen)
    for _ in range(MAX_DEPTH):
        above: list[tuple[str, str]] = []
        for node in frontier:
            text = await read(model_path(*node))
            if text is None:
                # Parent absent : ce n'est pas à ce module de le refuser —
                # `check_references` nomme déjà le modèle manquant, et deux refus pour un
                # seul manquement enverraient corriger deux fois le même document.
                continue
            for parent in parents_of(text):
                if parent not in seen:
                    seen.append(parent)
                    above.append(parent)
        if not above:
            return tuple(seen)
        frontier = above
    return None


async def cycle_problems(
    read: Reader, model: tuple[str, str], parent: tuple[str, str]
) -> list[Problem]:
    """Ce qui empêche `model` d'hériter de `parent`. Vide : il peut.

    Un seul test couvre les trois façons de boucler — se désigner soi-même, désigner son
    enfant, désigner plus loin dans sa propre descendance : il suffit que `model` soit
    au-dessus de `parent`.
    """
    above = await ancestors(read, (parent,))
    if above is None:
        return [Problem("allOf", TOO_DEEP, str(MAX_DEPTH))]
    if model in above:
        # Le détail montre la boucle qui se ferme, et non chaque intermédiaire : le
        # parcours est en largeur, donc il connaît l'ascendance, pas le chemin exact. Ce
        # qu'il faut corriger est de toute façon ce `$ref`-ci.
        return [Problem("allOf", RECURSIVE, _chain([model, parent, model]))]
    return []


def loop_problems(model: tuple[str, str], above: Ancestry) -> list[Problem]:
    """Le payload est dans sa propre ascendance : le schéma composé ne se valide pas.

    Distinct de `cycle_problems`, et les deux sont nécessaires : celui-là refuse le geste
    qui POSE un parent, en le nommant ; celui-ci regarde une ascendance DÉJÀ écrite — un
    fichier retouché hors de Miles, ou un modèle parent redirigé après coup par l'écran
    des modèles, qui ne connaît pas les events.
    """
    return [Problem("allOf", RECURSIVE, _chain([model, model]))] if model in above.models else []


@dataclass(frozen=True)
class Ancestry:
    """Ce qu'un payload tient de ses parents, et ce qui les rendrait inaptes à en être un."""

    models: tuple[tuple[str, str], ...]
    # Les propriétés héritées. Elles comptent partout où les propres propriétés du modèle
    # comptent : `UNIQUE (Montant)` est valide sur un event qui tient `Montant` de son
    # parent, parce que le moteur valide le schéma COMPOSÉ.
    properties: frozenset[str]
    problems: tuple[Problem, ...]


async def ancestry(read: Reader, parents: Sequence[tuple[str, str]]) -> Ancestry | None:
    """L'ascendance d'un payload : ses modèles, leurs propriétés, leurs manquements.

    `None` : l'ascendance est plus profonde que la borne, donc on ne la connaît pas.

    Un payload hérité se valide COMME UN TOUT : le moteur reçoit le schéma composé, pas le
    seul fichier de l'enfant. Un parent FERMÉ, ou qui redéclare une propriété du socle,
    rend donc l'enfant insatisfiable sans qu'aucun des deux fichiers ne paraisse faux —
    c'est exactement ce que le dépôt refuse de livrer, et c'est pourquoi les règles du
    payload s'appliquent aussi aux parents.
    """
    above = await ancestors(read, parents)
    if above is None:
        return None
    properties: set[str] = set()
    problems: list[Problem] = []
    for parent in above:
        text = await read(model_path(*parent))
        if text is None:
            continue
        try:
            schema = parse_schema(text)
        except ValueError:
            # `ModelSyntaxError` comme `ModelGrammarError` : un parent retouché hors de
            # Miles ne peut pas porter un payload, et ça se dit AVANT d'écrire la
            # déclaration qui en dépendrait.
            problems.append(Problem("allOf", "parent_non_conforme", _one(parent)))
            continue
        properties |= set(schema.properties)
        problems += [
            Problem("allOf", p.code, f"{_one(parent)} : {p.detail or p.path}")
            for p in payload_problems(text, schema)
        ]
    return Ancestry(above, frozenset(properties), tuple(problems))


def _one(model: tuple[str, str]) -> str:
    return f"{model[0]}/{model[1]}"


def _chain(models: list[tuple[str, str]]) -> str:
    """La boucle en clair : `shared/a → shared/b → shared/a`. Le refus doit la NOMMER."""
    return " → ".join(map(_one, models))


def _all_of(data: Any) -> list[Any]:
    items = data.get("allOf") if isinstance(data, dict) else None
    return list(items) if isinstance(items, list) else []


def _inherited(data: Any) -> list[tuple[int, tuple[str, str]]]:
    """(rang dans l'`allOf`, modèle désigné) de chaque entrée qui est un héritage."""
    found = []
    for index, item in enumerate(_all_of(data)):
        ref = item.get("$ref") if isinstance(item, dict) else None
        target = target_of(ref) if isinstance(ref, str) else None
        if target is not None:
            found.append((index, target))
    return found


def _with_all_of(data: dict[str, Any], entries: list[Any]) -> dict[str, Any]:
    """Le document, son `allOf` remplacé — à SA place, ou juste après `type`.

    La place est tenue pour que la redirection d'un héritage se lise comme un diff d'une
    ligne, et non comme une réécriture du fichier.
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key == "allOf":
            if entries:
                out["allOf"] = entries
            continue
        out[key] = value
        if key == "type" and entries and "allOf" not in data:
            out["allOf"] = entries
    if entries and "allOf" not in out:
        out["allOf"] = entries
    return out
