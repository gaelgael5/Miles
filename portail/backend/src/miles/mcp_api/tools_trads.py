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
from miles.workshop.trads_keys import PAGE_MAX, TradsKeysService
from miles.workshop.trads_service import TradsService

ContextName = Annotated[
    str,
    Field(description="Nom technique du contexte : son répertoire trads/<nom>/, figé."),
]
KeySlug = Annotated[
    str,
    Field(description="Slug de la clé, ce que le paramétrage référencera : figé sauf renommage."),
]
Values = Annotated[
    dict[str, str | None],
    Field(
        description=(
            "Valeur par code de culture. Une culture ABSENTE de la mappe n'est pas touchée et"
            " son fichier n'est pas réécrit ; null VIDE la valeur et retire sa ligne du"
            " fichier. La valeur de la culture par défaut du workspace est obligatoire."
        )
    ),
]


def _service(caller: Caller) -> TradsService:
    service: TradsService = caller.services.trads
    return service


def _keys(caller: Caller) -> TradsKeysService:
    service: TradsKeysService = caller.services.trads_keys
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


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, name: str) -> ToolError:
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

    @server.tool(
        description=(
            "Liste les clés d'un contexte et leurs valeurs par culture du workspace."
            " `search` filtre sur le slug ; `untranslated` ne rend que les clés SANS valeur"
            " dans cette culture — la liste de travail d'un traducteur. Une culture absente"
            " des valeurs n'est pas traduite ; elle n'y figure jamais avec une chaîne vide."
        )
    )
    async def list_trads_keys(
        workspace_id: Workspace,
        context: ContextName,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        search: Annotated[str, Field(description="Fragment du slug.")] = "",
        untranslated: Annotated[
            str | None, Field(description="Code de culture : les clés sans valeur dedans.")
        ] = None,
        offset: Annotated[int, Field(description="Rang de départ.", ge=0)] = 0,
        limit: Annotated[int, Field(description="Taille de page.", ge=1, le=PAGE_MAX)] = PAGE_MAX,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            page = await _keys(caller).resolve_page(
                caller.viewer,
                workspace_id,
                context,
                branch=branch,
                search=search,
                untranslated=untranslated,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            # AVANT `tool_refusal` : sa branche générique rendrait « contexte_inconnu »
            # sans la liste de ce qui existe, et l'agent n'aurait rien pour se corriger.
            if _is_unknown_context(exc):
                raise await _unknown(caller, workspace_id, branch, context) from None
            raise tool_refusal(exc) or exc from None
        return {
            "keys": [{"slug": k.slug, "values": dict(k.values)} for k in page.keys],
            "total": page.total,
        }

    @server.tool(
        description=(
            "Ajoute une clé à un contexte, avec ses valeurs. La valeur de la culture par"
            " défaut du workspace est obligatoire. Refus : slug_pris, slug invalide"
            " (minuscules, chiffres, tiret, souligné), valeur_par_defaut_obligatoire,"
            " direction_forcee (la valeur porte des caractères qui la feraient s'afficher"
            " autrement qu'elle n'est écrite ; le refus les nomme)."
        )
    )
    async def create_trads_key(
        workspace_id: Workspace,
        context: ContextName,
        slug: KeySlug,
        values: Values,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        return await _save(ctx, workspace_id, context, slug, values, branch, creating=True)

    @server.tool(
        description=(
            "Écrit les valeurs d'une clé existante, et SEULEMENT les cultures présentes dans"
            " `values` : les autres fichiers ne sont pas réécrits, ce qui garde le diff git"
            " lisible. null vide une valeur et retire sa ligne ; vider celle de la culture"
            " par défaut est refusé."
        )
    )
    async def update_trads_values(
        workspace_id: Workspace,
        context: ContextName,
        slug: KeySlug,
        values: Values,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        return await _save(ctx, workspace_id, context, slug, values, branch, creating=False)

    @server.tool(
        description=(
            "Renomme une clé dans TOUS les fichiers de cultures du contexte. C'est une"
            " RUPTURE, pas une correction : le slug est ce que le paramétrage référencera,"
            " et le produit ne sait pas encore dire ce qui pointe une clé."
        )
    )
    async def rename_trads_key(
        workspace_id: Workspace,
        context: ContextName,
        slug: KeySlug,
        new_slug: Annotated[str, Field(description="Nouveau slug.")],
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _keys(caller)

        async def run(author: Any) -> dict[str, Any]:
            commit = await service.resolve_rename(
                author, workspace_id, context, slug, new_slug, branch=branch
            )
            return {"slug": new_slug, "commit": commit}

        return await caller.write("rename_trads_key", workspace_id, branch, slug, run)

    @server.tool(
        description=(
            "Supprime une clé de tous les fichiers de cultures du contexte. Même régime que"
            " le renommage : personne ne sait encore qui la référence."
        )
    )
    async def delete_trads_key(
        workspace_id: Workspace,
        context: ContextName,
        slug: KeySlug,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _keys(caller)

        async def run(author: Any) -> dict[str, Any]:
            commit = await service.resolve_delete(
                author, workspace_id, context, slug, branch=branch
            )
            return {"deleted": slug, "commit": commit}

        return await caller.write("delete_trads_key", workspace_id, branch, slug, run)


async def _save(
    ctx: Context[Any, Request],
    workspace_id: str,
    context: str,
    slug: str,
    values: dict[str, str | None],
    branch: str | None,
    *,
    creating: bool,
) -> dict[str, Any]:
    """Création et mise à jour partagent le même geste : seul `creating` les sépare."""
    caller = caller_of(ctx)
    service = _keys(caller)
    name = "create_trads_key" if creating else "update_trads_values"

    async def run(author: Any) -> dict[str, Any]:
        commit = await service.resolve_save(
            author, workspace_id, context, slug, values, branch=branch, creating=creating
        )
        return {"slug": slug, "commit": commit, "written": sorted(values)}

    return await caller.write(name, workspace_id, branch, slug, run)


def _is_unknown_context(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "contexte_inconnu"
