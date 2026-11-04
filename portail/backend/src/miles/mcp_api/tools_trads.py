from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tools_models import ReadBranch, Workspace, WriteBranch
from miles.workshop.trads import Context as TradsContext
from miles.workshop.trads_service import TradsService

ContextName = Annotated[
    str,
    Field(description="Nom technique du contexte : son répertoire trads/<nom>/, figé."),
]


def _service(caller: Caller) -> TradsService:
    service: TradsService = caller.services.trads
    return service


def _context(context: TradsContext) -> dict[str, Any]:
    return {
        "name": context.name,
        "label": context.label,
        "path": f"trads/{context.name}/",
        "keys": context.keys,
        "translated": dict(context.translated),
        "obsolete": dict(context.obsolete),
    }


async def unknown_context(
    caller: Caller, workspace_id: str, branch: str | None, name: str
) -> ToolError:
    """Nomme les contextes qui existent : un agent corrige alors sans tâtonner."""
    found = await _service(caller).resolve_list(caller.viewer, workspace_id, branch=branch)
    return ToolError(refusal("contexte_inconnu", contexte=name, existants=[c.name for c in found]))


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les contextes de traduction d'une branche : leur nom technique, leur"
            " libellé, leur nombre de clés, les clés traduites par culture du workspace, et"
            " les cultures retirées du workspace dont le dépôt garde encore un fichier."
            " Le dépôt fait foi : un répertoire créé à la main y figure, avec son nom"
            " technique pour libellé."
        )
    )
    async def list_trads_contexts(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, Any]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            found = await _service(caller).resolve_list(caller.viewer, workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [_context(c) for c in found]

    @server.tool(
        description=(
            "Couverture des traductions d'une branche : le total de clés, puis pour chaque"
            " culture du workspace le nombre de clés traduites et manquantes, et enfin le"
            " détail contexte par contexte. `is_default` marque la culture par défaut du"
            " workspace — qu'une clé ne peut pas ne pas porter, et qui n'est PAS forcément"
            " en-US. `inconsistent` sur elle veut dire que le DÉPÔT est incohérent, pas"
            " qu'il reste à traduire ; `low` marque une culture sous le seuil rendu dans"
            " `threshold`. Pour obtenir la liste de travail elle-même, filtrer"
            " list_trads_keys sur `untranslated`."
        )
    )
    async def trads_coverage(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            coverage = await _service(caller).resolve_coverage(
                caller.viewer, workspace_id, branch=branch
            )
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return {
            "branch": coverage.branch,
            "default": coverage.default,
            "keys": coverage.keys,
            "threshold": coverage.threshold,
            "cultures": [
                {
                    "culture": row.culture,
                    "translated": row.translated,
                    "missing": row.missing,
                    "is_default": row.is_default,
                    "low": row.low,
                    "inconsistent": row.inconsistent,
                }
                for row in coverage.cultures
            ],
            "contexts": [_context(c) for c in coverage.contexts],
        }

    @server.tool(
        description=(
            "Crée un contexte et son répertoire trads/<nom>/ dans une branche enfant."
            " Le nom technique est FIGÉ après création : il entre dans le chemin sur disque"
            " et dans tout ce qui référencera ses clés. Refus : contexte_pris (le refus"
            " nomme le libellé du contexte existant)."
        )
    )
    async def create_trads_context(
        workspace_id: Workspace,
        name: ContextName,
        label: Annotated[str, Field(description="Libellé pour l'humain, sur une ligne.")],
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            commit = await service.resolve_add(author, workspace_id, name, label, branch=branch)
            return {"name": name, "label": label, "commit": commit}

        return await caller.write("create_trads_context", workspace_id, branch, name, run)

    @server.tool(
        description=(
            "Change le LIBELLÉ d'un contexte. Il n'existe aucun outil pour changer son nom"
            " technique : le renommer déplacerait des fichiers et casserait des références"
            " que le produit ne sait pas encore retrouver."
        )
    )
    async def rename_trads_context(
        workspace_id: Workspace,
        name: ContextName,
        label: Annotated[str, Field(description="Nouveau libellé.")],
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            commit = await service.resolve_relabel(author, workspace_id, name, label, branch=branch)
            return {"name": name, "label": label, "commit": commit}

        return await caller.write("rename_trads_context", workspace_id, branch, name, run)

    @server.tool(
        description=(
            "Supprime un contexte et TOUTES ses clés d'une branche enfant. Rend ce qui a"
            " disparu : le nombre de clés et le nombre de valeurs, toutes cultures"
            " confondues. C'est un commit, donc la suppression se relit et se défait."
        )
    )
    async def delete_trads_context(
        workspace_id: Workspace,
        name: ContextName,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            commit, removal = await service.resolve_delete(
                author, workspace_id, name, branch=branch
            )
            return {
                "deleted": name,
                "keys": removal.keys,
                "values": removal.values,
                "commit": commit,
            }

        return await caller.write("delete_trads_context", workspace_id, branch, name, run)
