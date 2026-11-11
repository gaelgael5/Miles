"""Les deux familles de schémas qu'une même primitive manipule : modèles et événements.

Décision de Gael du 11/11/2026 : **une seule série de primitives**, dont le premier
argument dit laquelle. Deux séries jumelles coûtaient à l'agent — il devait apprendre
deux fois les mêmes gestes, et un geste ajouté à l'une se serait un jour oublié dans
l'autre.

Ce qui reste propre à chaque famille n'est donc pas une primitive, c'est une RÈGLE, et
elle est écrite dans la description de l'outil : un événement se valide en plus contre le
socle commun du moteur, et son nom ne peut pas porter de tiret.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from miles.datamodels.layout import model_path
from miles.datamodels.service import ModelNotFoundError
from miles.mcp_api.calls import Caller
from miles.mcp_api.errors import refusal
from miles.workflowevents.layout import event_path
from miles.workflowevents.service import EventNotFoundError

MODEL = "model"
EVENT = "event"
KINDS = (MODEL, EVENT)

Kind = Annotated[
    str,
    Field(
        description=(
            "« model » pour un modèle de données, « event » pour un événement de workflow."
            " Les deux sont des JSON Schema 2020-12 écrits en YAML, dans DEUX listes"
            " séparées : un storage ou une source ne peut désigner qu'un modèle."
        )
    ),
]
Workspace = Annotated[str, Field(description="Identifiant du workspace (voir list_workspaces).")]
ReadBranch = Annotated[
    str | None,
    Field(description="Slug de la branche à lire ; absent : la branche de base du workspace."),
]
WriteBranch = Annotated[
    str | None,
    Field(
        description=(
            "Slug d'une branche ENFANT du workspace, obligatoire : la branche de base est en"
            " lecture seule. Le refus liste les branches enfants existantes. La personne pour"
            " qui vous appelez doit y avoir la main (refus prise_de_main_requise sinon) ; la"
            " modification reste locale jusqu'à publish_branch."
        )
    ),
]
Scope = Annotated[
    str,
    Field(
        description=(
            "« shared » pour un schéma transverse, sinon le nom d'un domaine existant"
            " (list_domains ; create_domain pour en ajouter un)."
        )
    ),
]
Name = Annotated[
    str,
    Field(
        description=(
            "Nom du schéma, celui de son fichier. Pour un ÉVÉNEMENT, c'est aussi le nom"
            " qu'un DEFINE EVENT écrira, et le tiret y est refusé : le DSL du moteur ne sait"
            " pas l'écrire (minuscules, chiffres et soulignés)."
        )
    ),
]


@dataclass(frozen=True)
class Family:
    """Ce qui diffère entre les deux familles, et rien de plus."""

    service: Any
    not_found: type[Exception]
    # Le code du refus « introuvable » : il NOMME la famille, pour qu'un agent ne cherche
    # pas un modèle quand c'est un événement qui manque.
    unknown_code: str
    # Le chemin du fichier, pour que le `path` d'un refus se lise dans le même vocabulaire
    # que la liste `existants` qui l'accompagne — des chemins de dépôt, pas « portée/nom ».
    path_of: Callable[[str, str], str]


def family_of(caller: Caller, kind: str) -> Family:
    if kind == MODEL:
        return Family(caller.services.data_models, ModelNotFoundError, "modele_inconnu", model_path)
    if kind == EVENT:
        return Family(
            caller.services.workflow_events,
            EventNotFoundError,
            "evenement_inconnu",
            event_path,
        )
    # `attendus` plutôt qu'un message : l'agent corrige sans relire la documentation.
    raise ToolError(refusal("champ_invalide", champ="kind", raison="forme", attendus=list(KINDS)))


def entry_out(entry: Any) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


def written_out(entry: Any, commit: str | None) -> dict[str, Any]:
    # Rejeu à l'identique : rien d'écrit, et la réponse le dit.
    return entry_out(entry) | {"commit": commit, "unchanged": commit is None}


async def unknown(
    caller: Caller,
    kind: str,
    workspace_id: str,
    branch: str | None,
    scope: str = "",
    name: str = "",
) -> ToolError:
    """Le refus « introuvable », avec ce qui existe : l'agent se corrige sans explorer.

    `path` dit ce qui a été DEMANDÉ et `existants` ce qu'il y a : les deux ensemble, parce
    qu'un agent qui ne voit que la liste ne sait pas lequel de ses appels a échoué.

    Et `path` est le chemin du FICHIER, comme avant l'unification du 11/11/2026 : un test
    d'intégration l'a rappelé en rougissant. Changer ce champ pour « portée/nom » aurait
    été une rupture de contrat que rien n'annonçait — et une incohérence, puisque la liste
    `existants` juste à côté porte des chemins de dépôt.
    """
    chosen = family_of(caller, kind)
    existing = await chosen.service.resolve_list(caller.viewer, workspace_id, branch=branch)
    return ToolError(
        refusal(
            chosen.unknown_code,
            kind=kind,
            path=chosen.path_of(scope, name) if scope and name else "",
            existants=[e.path for e in existing],
        )
    )
