from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.datamodels.service import DataModelsService, ModelEntry, ModelNotFoundError
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
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
            " lecture seule. Le refus liste les branches enfants existantes."
        )
    ),
]
Scope = Annotated[
    str, Field(description="« shared » pour un modèle transverse, sinon le nom du domaine.")
]
Name = Annotated[str, Field(description="Nom du modèle (celui de son fichier, sans extension).")]
Content = Annotated[
    str, Field(description="Le modèle en YAML, selon la grammaire des modèles de Miles.")
]


def _entry(entry: ModelEntry) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


def _written(entry: ModelEntry, commit: str | None) -> dict[str, Any]:
    # Rejeu à l'identique (critère 5) : rien d'écrit, et la réponse le dit.
    return _entry(entry) | {"commit": commit, "unchanged": commit is None}


async def _models(caller: Caller) -> DataModelsService:
    service: DataModelsService = caller.services.data_models
    return service


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, path: str) -> ToolError:
    """Un modèle inconnu, avec ce qui existe : l'agent se corrige sans appel exploratoire."""
    existing = await (await _models(caller)).resolve_list(workspace_id, branch=branch)
    return ToolError(refusal("modele_inconnu", path=path, existants=[e.path for e in existing]))


def register(server: MCPServer) -> None:
    @server.tool(description="Liste les modèles de données d'une branche, avec leur emplacement.")
    async def list_data_models(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, str]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            entries = await (await _models(caller)).resolve_list(workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [_entry(e) for e in entries]

    @server.tool(description="Lit un modèle de données : son emplacement et son YAML tel quel.")
    async def get_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
    ) -> dict[str, str]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        service = await _models(caller)
        try:
            entry, content = await service.resolve_get(workspace_id, scope, name, branch=branch)
        except ModelNotFoundError as exc:
            raise await _unknown(caller, workspace_id, branch, str(exc)) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _entry(entry) | {"content": content}

    @server.tool(
        description=(
            "Crée un modèle de données dans une branche enfant. Le nom vient du YAML. Refus"
            " structurés : yaml_invalide, modele_non_conforme (tous les écarts), nom_pris."
        )
    )
    async def create_data_model(
        workspace_id: Workspace,
        scope: Scope,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            entry, commit = await service.resolve_create(
                author, workspace_id, scope, content, branch=branch
            )
            return _written(entry, commit)

        return await caller.write("create_data_model", workspace_id, branch, scope, run)

    @server.tool(
        description=(
            "Remplace le YAML d'un modèle existant, dans une branche enfant. Le nom ne change"
            " pas par un remplacement (nom_fige) : renommer, c'est créer puis supprimer."
        )
    )
    async def replace_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                entry, commit = await service.resolve_replace(
                    author, workspace_id, scope, name, content, branch=branch
                )
            except ModelNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return _written(entry, commit)

        element = f"{scope}/{name}"
        return await caller.write("replace_data_model", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Supprime un modèle d'une branche enfant. Refusé (modele_utilise) tant qu'un autre"
            " modèle le désigne : le refus nomme lesquels."
        )
    )
    async def delete_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await service.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except ModelNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return {"deleted": f"{scope}/{name}", "commit": commit}

        element = f"{scope}/{name}"
        return await caller.write("delete_data_model", workspace_id, branch, element, run)
