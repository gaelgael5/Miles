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

from miles.datamodels.layout import model_path
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
            "« shared » pour un schéma transverse, sinon le nom d'un domaine existant"
            " (list_domains ; create_domain pour en ajouter un)."
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


def entry_out(entry: Any) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


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
            existants=[e.path for e in existing],
        )
    )
