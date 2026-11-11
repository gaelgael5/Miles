"""Les événements de workflow, pour un agent : lire, écrire, supprimer.

Même CRUD que les modèles de données (`tools_models.py`), et c'est voulu : un agent qui
construit un paramétrage touche aux deux, et deux surfaces dissemblables l'obligeraient à
apprendre deux fois la même chose. Ce qui diffère est écrit dans les descriptions, parce
que c'est là qu'un agent le lit : le socle commun qu'il ne doit pas redéclarer, et le nom
que le DSL du moteur contraint.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.workflowevents.layout import EventEntry
from miles.workflowevents.schema import socle_fields
from miles.workflowevents.service import EventNotFoundError, WorkflowEventsService

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
            "« shared » pour un événement transverse, sinon le nom d'un domaine existant"
            " (list_domains ; create_domain pour en ajouter un)."
        )
    ),
]
Name = Annotated[
    str,
    Field(
        description=(
            "Nom de l'événement, celui qu'un DEFINE EVENT écrira : minuscules, chiffres et"
            " soulignés, en commençant par une lettre ou un chiffre. Le TIRET est refusé —"
            " le DSL du moteur ne sait pas l'écrire."
        )
    ),
]
Content = Annotated[
    str,
    Field(
        description=(
            "L'événement : un JSON Schema 2020-12 écrit en YAML, dont la racine est un objet"
            " (type: object). `title` est son libellé. `$schema` et `$id` sont posés par Miles."
            " Le schéma décrit les données MÉTIER seulement : le moteur valide en plus un socle"
            " commun (voir get_event_base), dont les propriétés ne se redéclarent pas."
            " `additionalProperties: false` est refusé, car le socle rendrait alors tout payload"
            " réel invalide. Un modèle de données se désigne par $ref: miles:/shared/<nom> ou"
            " miles:/domains/<domaine>/<nom>."
        )
    ),
]


def _entry(entry: EventEntry) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


def _written(entry: EventEntry, commit: str | None) -> dict[str, Any]:
    # Rejeu à l'identique : rien d'écrit, et la réponse le dit.
    return _entry(entry) | {"commit": commit, "unchanged": commit is None}


async def _events(caller: Caller) -> WorkflowEventsService:
    service: WorkflowEventsService = caller.services.workflow_events
    return service


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, path: str) -> ToolError:
    """Un événement inconnu, avec ce qui existe : l'agent se corrige sans appel exploratoire."""
    existing = await (await _events(caller)).resolve_list(
        caller.viewer, workspace_id, branch=branch
    )
    return ToolError(refusal("evenement_inconnu", path=path, existants=[e.path for e in existing]))


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les événements de workflow d'une branche, avec leur emplacement. Ce sont"
            " les événements qu'un DEFINE EVENT peut désigner ; ils ne se mélangent pas aux"
            " modèles de données (list_data_models)."
        )
    )
    async def list_workflow_events(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, str]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            entries = await (await _events(caller)).resolve_list(
                caller.viewer, workspace_id, branch=branch
            )
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [_entry(e) for e in entries]

    @server.tool(description="Lit un événement de workflow : son emplacement et son YAML tel quel.")
    async def get_workflow_event(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
    ) -> dict[str, str]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        service = await _events(caller)
        try:
            entry, content = await service.resolve_get(
                caller.viewer, workspace_id, scope, name, branch=branch
            )
        except EventNotFoundError as exc:
            raise await _unknown(caller, workspace_id, branch, str(exc)) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _entry(entry) | {"content": content}

    @server.tool(
        description=(
            "Le socle commun que le moteur valide EN PLUS du schéma d'un événement. À lire"
            " avant d'écrire : ces propriétés existent déjà dans tout payload, et les"
            " redéclarer est refusé (propriete_du_socle). Lu du moteur installé, pas d'une"
            " liste tenue à la main."
        )
    )
    async def get_event_base(ctx: Context[Any, Request]) -> list[dict[str, Any]]:
        # Aucun workspace, aucune branche : la réponse ne dépend que du moteur installé.
        # Le portillon MCP s'applique quand même — c'est `caller_of` qui l'a déjà exigé.
        caller_of(ctx)
        return [
            {"name": nom, "type": type_declare, "read_only": lecture_seule}
            for nom, type_declare, lecture_seule in socle_fields()
        ]

    @server.tool(
        description=(
            "Crée un événement de workflow (JSON Schema 2020-12 en YAML) dans une branche"
            " enfant. Refus structurés : yaml_invalide, evenement_non_conforme (tous les"
            " écarts, dont schema_ferme et propriete_du_socle), nom_pris, domaine_inconnu."
        )
    )
    async def create_workflow_event(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _events(caller)

        async def run(author: Any) -> dict[str, Any]:
            entry, commit = await service.resolve_create(
                author, workspace_id, scope, name, content, branch=branch
            )
            return _written(entry, commit)

        element = f"{scope}/{name}"
        return await caller.write("create_workflow_event", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Remplace le schéma d'un événement existant, dans une branche enfant. Le nom ne"
            " change pas : renommer, c'est créer puis supprimer — et un script de workflow qui"
            " déclare l'ancien nom ne se chargera plus. La version monte de 1, tenue par Miles."
        )
    )
    async def replace_workflow_event(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _events(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                entry, commit = await service.resolve_replace(
                    author, workspace_id, scope, name, content, branch=branch
                )
            except EventNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return _written(entry, commit)

        element = f"{scope}/{name}"
        return await caller.write("replace_workflow_event", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Supprime un événement d'une branche enfant. Rien dans le paramétrage ne le"
            " désigne encore, donc aucun refus « utilisé » : c'est le script de workflow qui"
            " le déclare qui cessera de se charger."
        )
    )
    async def delete_workflow_event(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _events(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await service.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except EventNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return {"deleted": f"{scope}/{name}", "commit": commit}

        element = f"{scope}/{name}"
        return await caller.write("delete_workflow_event", workspace_id, branch, element, run)
