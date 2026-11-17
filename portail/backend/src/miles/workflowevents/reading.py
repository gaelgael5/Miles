"""Ce que la branche DÉCLARE, périmètre par périmètre.

Séparé du service le 17/11/2026, et pour une raison mesurée : la lecture vivait dans
`WorkflowEventsService`, donc elle ne s'éprouvait qu'avec un dépôt — c'est-à-dire sur la
machine de test. Une erreur d'une ligne (un périmètre SANS artefact passé à `parse`, qui
refuse le texte vide) est partie verte en local et a rougi dix tests de campagne.

Ici, la lecture ne prend qu'un `Reader` et la liste des chemins : le même contrat que
`miles.datamodels.usages`, et pour le même motif. Elle s'éprouve en une seconde, sans
dépôt ni forge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from miles.datamodels.layout import SHARED, ModelEntry, model_path
from miles.datamodels.layout import entry_of as model_entry_of
from miles.workflowevents.dsl import DslProblem, FragmentError, fragment_path, parse
from miles.workshop.domains import domains_in

# Lire UN fichier de la branche, ou None s'il n'y est pas.
Reader = Callable[[str], Awaitable[str | None]]


@dataclass(frozen=True)
class DeclaredType:
    """Un type d'event tel que l'artefact de son périmètre le déclare."""

    scope: str  # « shared », ou le nom du domaine
    name: str
    label: str
    # (portée, nom) du modèle qui décrit le payload, et son chemin : l'écran et la surface
    # MCP désignent un modèle par son chemin de dépôt, comme partout ailleurs.
    model: tuple[str, str]
    model_path: str
    unique: tuple[str, ...] = field(default=())
    # Le modèle désigné manque sur la branche. RENDU plutôt que refusé : une liste doit
    # montrer une déclaration orpheline — c'est ce qui bloque l'enregistrement d'une
    # version —, jamais la cacher.
    model_missing: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Perimeter:
    """Un périmètre et son artefact : ses types, ou ce qui empêche de les relire.

    Rendu pour TOUS les périmètres de la branche — « shared » et chaque domaine —, même
    ceux dont l'artefact n'existe pas : c'est la liste que l'écran déplie, et un périmètre
    qui n'apparaîtrait qu'une fois son premier type déclaré serait introuvable pour le
    déclarer (story `8a9ff6bc`, critères 1 et 6).
    """

    scope: str
    # Où l'artefact VIT, qu'il existe ou non : c'est le fichier que l'écran nomme quand il
    # n'est pas relisible, et celui qu'un geste écrira.
    path: str
    types: tuple[DeclaredType, ...] = field(default=())
    # Ce qui empêche de relire CET artefact. Non vide : `types` est vide, et ce n'est pas
    # « aucun type » — l'écran doit dire les deux choses différemment.
    problems: tuple[DslProblem, ...] = field(default=())


async def read_perimeters(read: Reader, paths: list[str]) -> tuple[Perimeter, ...]:
    """Les périmètres de la branche : « shared » d'abord, puis les domaines, par ordre.

    Un artefact qui ne se relit pas n'arrête QUE son périmètre, et ses manquements sont
    rendus avec lui. Ce n'est pas un assouplissement du tout-ou-rien : un périmètre rendu
    AVEC son erreur ne fait pas croire que ses types ont disparu — il nomme son fichier —,
    et l'écriture passe par `declared_in`, qui refuse en bloc.
    """
    known = {(e.scope, e.name) for e in _models(paths)}
    found = []
    for scope in [SHARED, *domains_in(paths)]:
        path = fragment_path(scope)
        text = await read(path)
        if text is None:
            # Pas d'artefact : le périmètre ne déclare rien, et ce n'est PAS une erreur.
            # Le passer à `parse` lèverait — le DSL refuse le texte vide, un FRAGMENT sans
            # déclaration étant une erreur de syntaxe. Mesuré en campagne le 17/11/2026 :
            # tout domaine sans type rendait la branche entière illisible.
            found.append(Perimeter(scope, path))
            continue
        try:
            declared = parse(text)
        except FragmentError as exc:
            found.append(Perimeter(scope, path, (), exc.problems))
            continue
        found.append(
            Perimeter(
                scope,
                path,
                tuple(
                    DeclaredType(
                        scope,
                        d.name,
                        d.label,
                        d.model,
                        model_path(*d.model),
                        d.unique,
                        d.model not in known,
                    )
                    for d in declared
                ),
            )
        )
    return tuple(found)


def declared_in(perimeters: tuple[Perimeter, ...]) -> list[DeclaredType]:
    """Tous les types, ou RIEN si un artefact ne se relit pas.

    Masquer un périmètre entier parce que son fichier a été retouché hors de Miles ferait
    croire que ses types ont disparu, et un geste de déclaration écrirait alors par-dessus
    ce qu'on n'a pas su relire. TOUTE écriture passe par ici.
    """
    problems = [p for perimeter in perimeters for p in perimeter.problems]
    if problems:
        raise FragmentError(problems)
    return [d for perimeter in perimeters for d in perimeter.types]


def _models(paths: list[str]) -> list[ModelEntry]:
    return [e for e in map(model_entry_of, paths) if e is not None]
