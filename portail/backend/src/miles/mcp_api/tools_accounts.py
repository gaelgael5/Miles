from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.accounts.service import AccountsService, ReferenceState, StorageUnknownError
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tools_models import ReadBranch, Workspace, WriteBranch

StorageName = Annotated[
    str,
    Field(description="Nom d'un storage de la branche : celui dont les objets sont les comptes."),
]


def _service(caller: Caller) -> AccountsService:
    service: AccountsService = caller.services.accounts
    return service


def _out(state: ReferenceState) -> dict[str, Any]:
    problem = state.problem
    return {
        "storage": None if state.reference is None else state.reference.storage,
        "model": state.model,
        "path": "comptes/reference.yaml",
        "problem": None
        if problem is None
        else {"path": problem.path, "code": problem.code, "detail": problem.detail},
    }


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "La référence de compte d'une branche : LE storage dont les objets sont les"
            " comptes associés aux devices, et le modèle que ce storage déclare. Le modèle"
            " est LU dans le storage, il n'est pas stocké avec la référence. `storage` à"
            " null veut dire qu'aucune référence n'est déclarée — ce n'est pas une erreur."
            " `problem` non nul veut dire que le dépôt se contredit : fichier illisible, ou"
            " storage désigné qui a disparu de la branche. Le réglage est DÉCLARÉ et pas"
            " encore servi : rien n'interroge ce storage, et aucun code n'est envoyé."
        )
    )
    async def get_account_reference(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            state = await _service(caller).resolve_get(caller.viewer, workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _out(state)

    @server.tool(
        description=(
            "Désigne le storage qui sert de référence de compte sur une branche enfant."
            " Une branche n'en a qu'UNE : appeler de nouveau remplace. Réécrire le même"
            " storage ne produit aucun commit et rend `unchanged` à vrai. Refus :"
            " storage_inconnu, dont le refus nomme les storages qui existent."
        )
    )
    async def set_account_reference(
        workspace_id: Workspace,
        storage: StorageName,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                saved = await service.resolve_save(author, workspace_id, storage, branch=branch)
            except StorageUnknownError as exc:
                # Nommés ICI et pas seulement comptés : un agent corrige alors sans
                # rappeler list_storages pour deviner ce qu'il a mal écrit.
                raise ToolError(
                    refusal("storage_inconnu", storage=exc.storage, existants=exc.known)
                ) from None
            return _out(saved.state) | {"unchanged": saved.unchanged}

        return await caller.write("set_account_reference", workspace_id, branch, storage, run)

    @server.tool(
        description=(
            "Retire la référence de compte d'une branche enfant. Sur une branche qui n'en"
            " porte aucune : sans effet, `removed` à faux, aucun commit — un rejeu ne"
            " doit pas échouer."
        )
    )
    async def remove_account_reference(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: WriteBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            return {"removed": await service.resolve_remove(author, workspace_id, branch=branch)}

        return await caller.write("remove_account_reference", workspace_id, branch, "", run)
