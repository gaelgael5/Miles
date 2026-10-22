from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request
from starlette.types import ASGIApp

from miles.apikeys.model import KeyPrincipal
from miles.mcp_api import tools_chains, tools_models
from miles.mcp_api.auth import ACTOR_STATE, PRINCIPAL_STATE, SERVICES_STATE, ApiKeyAuth
from miles.mcp_api.calls import caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.obo.service import Actor
from miles.workshop.target import base_slug
from miles.workspaces.service import WorkspacesService

INSTRUCTIONS = (
    "Miles : back-office du terminal point relais. Le paramétrage (modèles de données,"
    " chaînes de transformations…) vit dans des branches de travail d'un workspace."
    " Commencez par list_workspaces : seuls les workspaces ouverts à votre clé y figurent."
    " Une modification exige une branche enfant ; la branche de base est en lecture seule."
)


def _request(ctx: Context[Any, Request]) -> Request:
    request = ctx.request_context.request
    if request is None:
        # Seul le transport HTTP porte une requête, et Miles n'en sert pas d'autre.
        raise ToolError(refusal("cle_requise"))
    return request


def principal_of(ctx: Context[Any, Request]) -> KeyPrincipal:
    principal: KeyPrincipal | None = getattr(_request(ctx).state, PRINCIPAL_STATE, None)
    if principal is None:
        # Inatteignable derrière ApiKeyAuth : fermé quand même, si la garde venait à manquer.
        raise ToolError(refusal("cle_requise"))
    return principal


def actor_of(ctx: Context[Any, Request]) -> Actor | None:
    """La personne pour qui le portail appelle, si sa signature OBO est valide."""
    actor: Actor | None = getattr(_request(ctx).state, ACTOR_STATE, None)
    return actor


def services_of(ctx: Context[Any, Request]) -> Any:
    """L'état de l'app Miles (ses services), posé par la garde sur la requête."""
    return getattr(_request(ctx).state, SERVICES_STATE)


def build_server() -> MCPServer:
    server = MCPServer("miles", instructions=INSTRUCTIONS)

    @server.tool(
        description=(
            "Liste les workspaces ouverts à cette clé, avec le droit qu'elle y a"
            " (lecture ou ecriture) et le slug de leur branche de base (lecture seule)."
        )
    )
    async def list_workspaces(ctx: Context[Any, Request]) -> list[dict[str, Any]]:
        principal = principal_of(ctx)
        workspaces: WorkspacesService = services_of(ctx).workspaces
        visible = []
        # Seuls les workspaces où la clé a un droit : un autre n'existe pas pour elle
        # (critère 7), il n'apparaît ni ici ni dans un refus.
        for workspace in await workspaces.resolve_list():
            access = principal.access_to(workspace.id)
            if access is not None:
                visible.append(
                    {
                        "id": workspace.id,
                        "name": workspace.name,
                        "access": access.value,
                        "base_branch": base_slug(workspace),
                    }
                )
        return visible

    @server.tool(
        description=(
            "Liste les branches d'un workspace : la branche de base (base: true, lecture"
            " seule) et ses branches enfants, seules cibles possibles d'une modification."
        )
    )
    async def list_branches(
        workspace_id: Annotated[str, Field(description="Identifiant du workspace.")],
        ctx: Context[Any, Request],
    ) -> list[dict[str, Any]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            entries = await caller.services.branches.resolve_list(workspace_id)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [{"slug": e.slug, "label": e.label, "base": e.base} for e in entries]

    @server.tool(
        description=(
            "Dit sous quelle clé l'appel est servi, et pour quelle personne quand le portail"
            " l'a signée (OBO) : c'est elle qui signera les modifications, « via » la clé."
        )
    )
    async def whoami(ctx: Context[Any, Request]) -> dict[str, Any]:
        principal, actor = principal_of(ctx), actor_of(ctx)
        return {
            "key": principal.label,
            "acting_for": None if actor is None else actor.display_name,
        }

    tools_models.register(server)
    tools_chains.register(server)
    return server


def mcp_app(server: MCPServer) -> ASGIApp:
    """Surface MCP montée sous /mcp/, derrière la garde par clé."""
    app = server.streamable_http_app(
        streamable_http_path="/",
        # Sans état : la gateway ouvre une session par appel, et une réponse JSON unique
        # suffit à des outils qui ne rappellent jamais le client.
        stateless_http=True,
        json_response=True,
        # Protection DNS rebinding coupée, volontairement : elle protège des appels
        # qu'un navigateur fait avec des droits ambiants (cookie). Ici le seul droit
        # est une clé en en-tête, qu'une page tierce n'a pas ; et le Host vu derrière
        # nginx et la gateway n'est pas connu d'avance.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return ApiKeyAuth(app)
