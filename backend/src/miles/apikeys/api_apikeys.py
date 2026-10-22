from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.apikeys.model import Access, ApiKeyInfo
from miles.apikeys.service import (
    ApiKeyNotFoundError,
    ApiKeyRevokedError,
    ApiKeysService,
    UnknownWorkspaceError,
)
from miles.auth.author import request_author
from miles.workspaces.model import WorkspaceInputError

# Réservé à l'administrateur, comme toute route que la passerelle ne liste pas : une
# session OIDC ordinaire n'y entre pas. La clé elle-même n'ouvre jamais ces routes.
router = APIRouter(prefix="/api/api-keys")


def api_keys_service(request: Request) -> ApiKeysService:
    service: ApiKeysService = request.app.state.api_keys
    return service


Service = Annotated[ApiKeysService, Depends(api_keys_service)]


class GrantIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(max_length=63)
    access: Access


class GrantsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grants: list[GrantIO] = Field(max_length=200)


class IssueIn(GrantsIn):
    label: str = Field(max_length=200)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    prefix: str
    grants: list[GrantIO]
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    last_used_at: datetime | None


class IssuedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ApiKeyOut
    # Rendue cette seule fois (critère 1) : Miles n'en garde que l'empreinte.
    secret: str


def _out(info: ApiKeyInfo) -> ApiKeyOut:
    return ApiKeyOut(
        id=info.id,
        label=info.label,
        prefix=info.prefix,
        grants=[GrantIO(workspace_id=g.workspace_id, access=g.access) for g in info.grants],
        created_at=info.created_at,
        created_by=info.created_by,
        revoked_at=info.revoked_at,
        last_used_at=info.last_used_at,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


def _grants(body: GrantsIn) -> dict[str, Access] | JSONResponse:
    grants = {g.workspace_id: g.access for g in body.grants}
    if len(grants) != len(body.grants):
        # Deux droits sur un même workspace : lequel vaudrait ? On ne choisit pas.
        return _error(422, {"field": "grants", "reason": "workspace_en_double"})
    return grants


_REFUSALS = (ApiKeyNotFoundError, ApiKeyRevokedError, UnknownWorkspaceError, WorkspaceInputError)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiKeyNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "cle_inconnue")
    if isinstance(exc, ApiKeyRevokedError):
        return _error(status.HTTP_409_CONFLICT, "cle_revoquee")
    if isinstance(exc, UnknownWorkspaceError):
        detail = {"field": "grants", "reason": "workspace_inconnu", "workspace": exc.workspace_id}
        return _error(422, detail)
    reason = exc.reason if isinstance(exc, WorkspaceInputError) else None
    return _error(422, {"field": "label", "reason": reason})


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(service: Service) -> object:
    return [_out(info) for info in await service.resolve_list()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=IssuedOut)
async def issue_key(
    body: IssueIn, request: Request, response: Response, service: Service
) -> object:
    grants = _grants(body)
    if isinstance(grants, JSONResponse):
        return grants
    try:
        info, secret = await service.resolve_issue(request_author(request), body.label, grants)
    except _REFUSALS as exc:
        return _refusal(exc)
    # La réponse porte la clé en clair : aucun cache, ni navigateur ni intermédiaire.
    response.headers["Cache-Control"] = "no-store"
    return IssuedOut(key=_out(info), secret=secret)


@router.put("/{key_id}/grants", response_model=ApiKeyOut)
async def set_grants(key_id: str, body: GrantsIn, request: Request, service: Service) -> object:
    grants = _grants(body)
    if isinstance(grants, JSONResponse):
        return grants
    try:
        return _out(await service.resolve_set_grants(request_author(request), key_id, grants))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(key_id: str, request: Request, response: Response, service: Service) -> object:
    try:
        info, already = await service.resolve_revoke(request_author(request), key_id)
    except _REFUSALS as exc:
        return _refusal(exc)
    if already:
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(info)
