from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.mcp_api.server import MCP_PATH
from miles.oauth.clients import ClientNotFoundError, OAuthClient, OAuthClientsService
from miles.workspaces.model import WorkspaceInputError

# Réservé à l'administrateur, comme toute route que la passerelle ne liste pas.
router = APIRouter(prefix="/api/oauth-clients")

# Adresses de retour de claude.ai, proposées à la déclaration (doc claude.ai, « Add a
# connector that isn't in the directory ») : l'administrateur les garde ou les change.
CLAUDE_CALLBACKS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)


def clients_service(request: Request) -> OAuthClientsService:
    service: OAuthClientsService = request.app.state.oauth_clients
    return service


Service = Annotated[OAuthClientsService, Depends(clients_service)]


class ClientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=200)
    redirect_uris: list[str] = Field(max_length=10)


class ClientOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    redirect_uris: list[str]
    created_at: datetime


class EndpointsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None partout : MILES_PUBLIC_URL absente, et OAuth fermé tant qu'elle manque.
    mcp_url: str | None
    issuer: str | None
    authorization_endpoint: str | None
    token_endpoint: str | None
    suggested_redirect_uris: list[str]


def _out(client: OAuthClient) -> ClientOut:
    return ClientOut(
        id=client.id,
        label=client.label,
        redirect_uris=list(client.redirect_uris),
        created_at=client.created_at,
    )


@router.get("/endpoints", response_model=EndpointsOut)
async def endpoints(request: Request) -> EndpointsOut:
    public_url: str | None = getattr(request.app.state, "public_url", None)
    base = public_url or ""
    return EndpointsOut(
        mcp_url=public_url and base + MCP_PATH,
        issuer=public_url,
        authorization_endpoint=public_url and f"{base}/oauth/authorize",
        token_endpoint=public_url and f"{base}/oauth/token",
        suggested_redirect_uris=list(CLAUDE_CALLBACKS),
    )


@router.get("", response_model=list[ClientOut])
async def list_clients(service: Service) -> object:
    return [_out(c) for c in await service.resolve_list()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ClientOut)
async def declare_client(body: ClientIn, request: Request, service: Service) -> object:
    try:
        client = await service.resolve_create(
            request_author(request), body.label, body.redirect_uris
        )
    except WorkspaceInputError as exc:
        return JSONResponse(status_code=422, content={"detail": {"field": exc.field}})
    return _out(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: str, request: Request, service: Service) -> Response:
    try:
        await service.resolve_delete(request_author(request), client_id)
    except ClientNotFoundError:
        return JSONResponse(status_code=404, content={"detail": "client_inconnu"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
