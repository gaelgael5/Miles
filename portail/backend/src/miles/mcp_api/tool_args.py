"""Les annotations que partagent les primitives de la surface MCP, et le refus « introuvable ».

Le module s'appelait `families.py` jusqu'au 14/11/2026, et le nom disait ce qu'il portait
alors — deux familles de schémas. Il ne porte plus de famille : ce sont les arguments
communs à toutes les primitives (workspace, branche de lecture, branche d'écriture) et les
sorties des primitives de schéma. Un nom qui ne dit plus ce qu'il contient se fait mal
ranger, et c'est la même raison qui a fait passer `messages/` à `models/` dans le dépôt.

La famille « événement » a disparu avec ce qui la fondait : un type d'event n'est plus un
document, c'est une DÉCLARATION (`DEFINE EVENT … AS @modele`) de l'artefact de son
périmètre, et le schéma de son payload est un modèle comme un autre.

**`kind` est donc retiré des primitives**, et c'est une rupture assumée : le laisser avec
une seule valeur admise aurait demandé à chaque appel de choisir entre une chose et rien.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from miles.datamodels.layout import ModelEntry, model_path
from miles.datamodels.usages import Listing
from miles.mcp_api.calls import Caller
from miles.mcp_api.errors import refusal

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
            "« shared » pour un schéma transverse, « devices-inbound » pour un message que"
            " le terminal envoie à Miles, « devices-outbound » pour un message que Miles"
            " envoie au terminal, sinon le nom d'un domaine existant (list_domains ;"
            " create_domain pour en ajouter un). Un schéma de domaine ne désigne que son"
            " domaine et les transverses ; un schéma device, que les transverses et les"
            " devices de son sens."
        )
    ),
]
Name = Annotated[
    str,
    Field(
        description=(
            "Nom du schéma, celui de son fichier : minuscules, chiffres, - et _. Un modèle"
            " destiné à devenir un TYPE D'EVENT ne porte pas de tiret — le DSL du moteur ne"
            " sait pas écrire `AS @shared.mon-modele`."
        )
    ),
]


def entry_out(entry: ModelEntry) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


def listed_out(listing: Listing) -> list[dict[str, str]]:
    """La liste des modèles pour l'agent : l'emplacement de chacun, et rien de plus.

    UN SEUL endroit TYPÉ traverse la forme que `resolve_list` rend, et c'est exprès :
    `Caller.services` est `Any` — il porte l'`app.state`, dont les attributs ne sont pas
    déclarés —, donc mypy ne voit rien de ce qu'un outil MCP fait d'un service. Le 16/11/2026,
    `resolve_list` est passé d'une liste à un objet et `list_schemas` a continué de l'itérer :
    style, types et 936 tests unitaires sont restés verts, et c'est la campagne
    d'intégration qui l'a dit, 65 minutes plus tard. Ici, le corps est vérifié.

    Les usages ne sont PAS rendus : un agent qui lit un modèle pour l'écrire n'en a que
    faire, et `read_usages` les fait payer à l'écran qui les montre. Ils entreront le jour
    où une primitive les demandera.
    """
    return [entry_out(listed.entry) for listed in listing.models]


def written_out(entry: Any, commit: str | None) -> dict[str, Any]:
    # Rejeu à l'identique : rien d'écrit, et la réponse le dit.
    return entry_out(entry) | {"commit": commit, "unchanged": commit is None}


async def unknown(
    caller: Caller,
    workspace_id: str,
    branch: str | None,
    scope: str = "",
    name: str = "",
) -> ToolError:
    """Le refus « introuvable », avec ce qui existe : l'agent se corrige sans explorer.

    `path` dit ce qui a été DEMANDÉ et `existants` ce qu'il y a : les deux ensemble, parce
    qu'un agent qui ne voit que la liste ne sait pas lequel de ses appels a échoué.

    Et `path` est le chemin du FICHIER : un test d'intégration l'a rappelé en rougissant le
    11/11/2026. Changer ce champ pour « portée/nom » aurait été une rupture de contrat que
    rien n'annonçait — et une incohérence, puisque la liste `existants` juste à côté porte
    des chemins de dépôt.
    """
    existing = await caller.services.data_models.resolve_list(
        caller.viewer, workspace_id, branch=branch
    )
    return ToolError(
        refusal(
            "modele_inconnu",
            path=model_path(scope, name) if scope and name else "",
            existants=[entry["path"] for entry in listed_out(existing)],
        )
    )
