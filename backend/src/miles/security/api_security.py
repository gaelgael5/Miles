from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.sessions import Session
from miles.events.model import LOCAL_DIRECTORY, EventAuthor
from miles.security.service import (
    SecurityInput,
    SecurityInputError,
    SecurityService,
    SecurityServiceExistsError,
    SecurityServiceNotFoundError,
    SecurityServices,
)

# Réservé à l'administrateur : la passerelle refuse toute autre session (403).
router = APIRouter(prefix="/api/security-services")


def security_services(request: Request) -> SecurityServices:
    service: SecurityServices = request.app.state.security
    return service


Services = Annotated[SecurityServices, Depends(security_services)]


class SecurityServiceOut(BaseModel):
    """Le secret n'apparaît que par le slug du secret qui le porte."""

    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    base_url: str
    realm: str
    client_id: str
    client_secret_slug: str
    last_check_outcome: str | None
    last_check_at: datetime | None
    # Installations qu'une modification toucherait : l'écran avertit avant de valider.
    dependent_installations: int


class SecurityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    realm: str
    client_id: str
    client_secret_slug: str

    def to_input(self) -> SecurityInput:
        return SecurityInput(self.base_url, self.realm, self.client_id, self.client_secret_slug)


class SecurityCreate(SecurityBody):
    id: str


async def _out(services: SecurityServices, s: SecurityService) -> SecurityServiceOut:
    return SecurityServiceOut(
        id=s.id,
        kind=s.kind,
        base_url=s.base_url,
        realm=s.realm,
        client_id=s.client_id,
        client_secret_slug=s.client_secret_slug,
        last_check_outcome=s.last_check_outcome,
        last_check_at=s.last_check_at,
        dependent_installations=await services.dependent_installations(s.id),
    )


def _author(request: Request) -> EventAuthor:
    session: Session = request.state.session
    return EventAuthor(LOCAL_DIRECTORY, session.subject)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (SecurityInputError, SecurityServiceExistsError, SecurityServiceNotFoundError)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, SecurityInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": exc.field})
    if isinstance(exc, SecurityServiceExistsError):
        return _error(status.HTTP_409_CONFLICT, "service_deja_declare")
    if isinstance(exc, SecurityServiceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "service_inconnu")
    raise exc


@router.get("", response_model=list[SecurityServiceOut])
async def list_services(services: Services) -> list[SecurityServiceOut]:
    return [await _out(services, s) for s in await services.resolve_list()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SecurityServiceOut)
async def declare_service(body: SecurityCreate, request: Request, services: Services) -> object:
    try:
        declared = await services.resolve_declare(_author(request), body.id, body.to_input())
    except _REFUSALS as exc:
        return _refusal(exc)
    return await _out(services, declared)


@router.put("/{service_id}", response_model=SecurityServiceOut)
async def update_service(
    service_id: str, body: SecurityBody, request: Request, services: Services
) -> object:
    try:
        updated = await services.resolve_update(_author(request), service_id, body.to_input())
    except _REFUSALS as exc:
        return _refusal(exc)
    return await _out(services, updated)


@router.post("/{service_id}/verification", response_model=SecurityServiceOut)
async def verify_service(service_id: str, services: Services) -> object:
    try:
        return await _out(services, await services.resolve_verify(service_id))
    except _REFUSALS as exc:
        return _refusal(exc)
