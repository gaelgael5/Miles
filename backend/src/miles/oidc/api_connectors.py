from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.sessions import Session
from miles.events.model import LOCAL_DIRECTORY, EventAuthor
from miles.oidc.model import (
    DEFAULT_SCOPES,
    Connector,
    ConnectorIdTakenError,
    ConnectorInput,
    ConnectorInputError,
    ConnectorInUseError,
    ConnectorNotFoundError,
)
from miles.oidc.service import IssuerUnreachableError, OidcService

# Administration des connecteurs : la passerelle n'y laisse passer que le compte
# d'amorçage, une session OIDC sans rôle y reçoit 403.
router = APIRouter(prefix="/api/oidc/connectors")


def oidc_service(request: Request) -> OidcService:
    service: OidcService = request.app.state.oidc
    return service


Service = Annotated[OidcService, Depends(oidc_service)]


class ConnectorOut(BaseModel):
    """Le secret client n'apparaît que par le slug du secret qui le porte."""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    issuer: str
    client_id: str
    client_secret_slug: str
    scopes: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ConnectorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    issuer: str
    client_id: str
    client_secret_slug: str
    scopes: str = DEFAULT_SCOPES
    active: bool = True

    def to_input(self) -> ConnectorInput:
        return ConnectorInput(
            issuer=self.issuer,
            client_id=self.client_id,
            client_secret_slug=self.client_secret_slug,
            scopes=self.scopes,
            active=self.active,
            label=self.label,
        )


class ConnectorCreate(ConnectorBody):
    id: str


def _out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=c.id,
        label=c.label,
        issuer=c.issuer,
        client_id=c.client_id,
        client_secret_slug=c.client_secret_slug,
        scopes=c.scopes,
        active=c.active,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _author(request: Request) -> EventAuthor:
    session: Session = request.state.session
    return EventAuthor(LOCAL_DIRECTORY, session.subject)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    ConnectorInputError,
    ConnectorIdTakenError,
    ConnectorNotFoundError,
    ConnectorInUseError,
)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, IssuerUnreachableError):
        unreachable = {"field": "issuer", "reason": "injoignable"}
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, unreachable)
    if isinstance(exc, ConnectorInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": exc.field})
    if isinstance(exc, ConnectorIdTakenError):
        return _error(status.HTTP_409_CONFLICT, "identifiant_pris")
    if isinstance(exc, ConnectorInUseError):
        in_use = {"code": "connecteur_utilise", "identities": exc.identities}
        return _error(status.HTTP_409_CONFLICT, in_use)
    if isinstance(exc, ConnectorNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "connecteur_inconnu")
    raise exc


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(service: Service) -> list[ConnectorOut]:
    return [_out(c) for c in await service.resolve_list(only_active=False)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConnectorOut)
async def create_connector(body: ConnectorCreate, request: Request, service: Service) -> object:
    try:
        return _out(await service.resolve_create(_author(request), body.id, body.to_input()))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.put("/{connector_id}", response_model=ConnectorOut)
async def update_connector(
    connector_id: str, body: ConnectorBody, request: Request, service: Service
) -> object:
    try:
        return _out(await service.resolve_update(_author(request), connector_id, body.to_input()))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(connector_id: str, request: Request, service: Service) -> Response:
    try:
        await service.resolve_delete(_author(request), connector_id)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
