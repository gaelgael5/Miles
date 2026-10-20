from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.sessions import Session
from miles.events.model import LOCAL_DIRECTORY, EventAuthor
from miles.secrets.model import (
    SecretInputError,
    SecretInUseError,
    SecretNotFoundError,
    SecretSlugTakenError,
    SecretSummary,
)
from miles.secrets.service import SecretsService

router = APIRouter(prefix="/api/secrets")


def secrets_service(request: Request) -> SecretsService:
    service: SecretsService = request.app.state.secrets
    return service


Service = Annotated[SecretsService, Depends(secrets_service)]


class ConsumerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    id: str


class SecretOut(BaseModel):
    """Ce que l'API rend d'un secret. Aucun champ ne porte la valeur, ni chiffrée."""

    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    secret_type: str
    created_at: datetime
    updated_at: datetime
    consumers: list[ConsumerOut]


# Pas de contrainte de longueur déclarée sur `value` : pydantic recopierait la valeur
# fautive dans sa réponse 422. Le socle la valide et ne renvoie que le nom du champ.
class SecretCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    secret_type: str
    value: str


class SecretRelabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class SecretValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


def _out(summary: SecretSummary) -> SecretOut:
    return SecretOut(
        slug=summary.slug,
        label=summary.label,
        secret_type=summary.secret_type,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        consumers=[ConsumerOut(kind=c.kind, id=c.id) for c in summary.consumers],
    )


def _author(request: Request) -> EventAuthor:
    # La passerelle a posé la session : seul le compte d'amorçage en ouvre une pour
    # l'instant, d'où l'annuaire « local ».
    session: Session = request.state.session
    return EventAuthor(LOCAL_DIRECTORY, session.subject)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, SecretInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": exc.field})
    if isinstance(exc, SecretSlugTakenError):
        return _error(status.HTTP_409_CONFLICT, "slug_pris")
    if isinstance(exc, SecretInUseError):
        consumers = [{"kind": c.kind, "id": c.id} for c in exc.consumers]
        return _error(status.HTTP_409_CONFLICT, {"code": "secret_utilise", "consumers": consumers})
    if isinstance(exc, SecretNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "secret_inconnu")
    raise exc


_REFUSALS = (SecretInputError, SecretSlugTakenError, SecretInUseError, SecretNotFoundError)


@router.get("", response_model=list[SecretOut])
async def list_secrets(service: Service, secret_type: str | None = None) -> object:
    try:
        return [_out(s) for s in await service.resolve_list(secret_type)]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{slug}", response_model=SecretOut)
async def get_secret(slug: str, service: Service) -> object:
    try:
        return _out(await service.resolve_get(slug))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SecretOut)
async def create_secret(body: SecretCreate, request: Request, service: Service) -> object:
    try:
        summary = await service.resolve_create(
            _author(request), body.slug, body.label, body.secret_type, body.value
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(summary)


@router.patch("/{slug}", response_model=SecretOut)
async def relabel_secret(
    slug: str, body: SecretRelabel, request: Request, service: Service
) -> object:
    try:
        return _out(await service.resolve_relabel(_author(request), slug, body.label))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.put("/{slug}/value", status_code=status.HTTP_204_NO_CONTENT)
async def replace_secret_value(
    slug: str, body: SecretValue, request: Request, service: Service
) -> Response:
    try:
        await service.resolve_replace_value(_author(request), slug, body.value)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(slug: str, request: Request, service: Service) -> Response:
    try:
        await service.resolve_delete(_author(request), slug)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
