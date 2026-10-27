from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.gitaccess.connections import ConnectionInput, ConnectionsService
from miles.gitaccess.model import (
    DependentCheckFailedError,
    DependentOutsideError,
    GitAccessConflictError,
    GitAccessInputError,
    GitAccessInUseError,
    GitAccessNotFoundError,
    GitConnection,
)
from miles.workspaces.model import report_json

# Réservées à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session.
connections_router = APIRouter(prefix="/api/git-connections")


def connections_service(request: Request) -> ConnectionsService:
    service: ConnectionsService = request.app.state.git_connections
    return service


Connections = Annotated[ConnectionsService, Depends(connections_service)]


class ConnectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    base_url: str
    token_secret_slug: str
    workspaces: list[str]
    created_at: datetime
    updated_at: datetime


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    base_url: str
    # Obligatoire, mais refusé par le service plutôt que par pydantic : le refus garde
    # alors la forme {field} que l'écran sait nommer.
    token_secret_slug: str | None = None


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    base_url: str
    token_secret_slug: str | None = None
    verification_suffix: str


def _connection(c: GitConnection) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        label=c.label,
        base_url=c.base_url,
        token_secret_slug=c.token_secret_slug,
        workspaces=list(c.workspaces),
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


_REFUSALS = (
    GitAccessInputError,
    GitAccessConflictError,
    GitAccessNotFoundError,
    GitAccessInUseError,
    DependentCheckFailedError,
    DependentOutsideError,
)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, GitAccessInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, DependentCheckFailedError):
        failed = exc.report.failed()
        detail = {
            "code": "acces_insuffisant",
            "workspace": exc.workspace_id,
            "right": failed.right.value if failed else None,
            "reason": failed.reason.value if failed and failed.reason else None,
            "report": report_json(exc.report),
        }
        return _error(unprocessable, detail)
    if isinstance(exc, DependentOutsideError):
        return _error(unprocessable, {"code": "depot_hors_adresse", "workspace": exc.workspace_id})
    if isinstance(exc, GitAccessInUseError):
        return _error(status.HTTP_409_CONFLICT, {"code": "utilise", "by": list(exc.users)})
    if isinstance(exc, GitAccessConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, GitAccessNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, f"{exc.kind}_inconnu")
    raise exc


def _replayed(response: Response, existed: bool) -> None:
    if existed:
        # Rejeu à l'identique : rien de créé, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"


@connections_router.get("", response_model=list[ConnectionOut])
async def list_connections(service: Connections) -> list[ConnectionOut]:
    return [_connection(c) for c in await service.resolve_list()]


@connections_router.post("", status_code=status.HTTP_201_CREATED, response_model=ConnectionOut)
async def create_connection(
    body: ConnectionCreate, request: Request, response: Response, service: Connections
) -> object:
    data = ConnectionInput(body.id, body.label, body.base_url, body.token_secret_slug)
    try:
        created, existed = await service.resolve_create(request_author(request), data)
    except _REFUSALS as exc:
        return _refusal(exc)
    _replayed(response, existed)
    return _connection(created)


@connections_router.put("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: str, body: ConnectionUpdate, request: Request, service: Connections
) -> object:
    data = ConnectionInput(connection_id, body.label, body.base_url, body.token_secret_slug)
    try:
        updated = await service.resolve_update(
            request_author(request), data, body.verification_suffix
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _connection(updated)


@connections_router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: str, request: Request, service: Connections) -> Response:
    try:
        await service.resolve_delete(request_author(request), connection_id)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
