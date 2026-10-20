from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.workspaces.service import (
    AccessCheckFailedError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceInput,
    WorkspaceInputError,
    WorkspaceNotFoundError,
    WorkspacesService,
    report_json,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session.
router = APIRouter(prefix="/api/workspaces")


def workspaces_service(request: Request) -> WorkspacesService:
    service: WorkspacesService = request.app.state.workspaces
    return service


Service = Annotated[WorkspacesService, Depends(workspaces_service)]


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    repo_url: str
    git_secret_slug: str
    # Absent : le workspace le dit explicitement, au lieu d'échouer à l'usage.
    security_service_id: str | None
    last_check: dict[str, Any] | None
    last_check_at: datetime | None
    created_at: datetime


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    repo_url: str
    git_secret_slug: str | None = None
    security_service_id: str | None = None
    # Choisi par l'écran, pour afficher le nom de la branche de vérification PENDANT
    # l'essai (critère 5), pas seulement en cas d'échec.
    verification_suffix: str


class RecheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_suffix: str


def _out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=w.id,
        name=w.name,
        repo_url=w.repo_url,
        git_secret_slug=w.git_secret_slug,
        security_service_id=w.security_service_id,
        last_check=w.last_check,
        last_check_at=w.last_check_at,
        created_at=w.created_at,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    WorkspaceInputError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    AccessCheckFailedError,
)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, WorkspaceInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": exc.field})
    if isinstance(exc, AccessCheckFailedError):
        failed = exc.report.failed()
        detail = {
            "code": "acces_insuffisant",
            "right": failed.right.value if failed else None,
            "reason": failed.reason.value if failed and failed.reason else None,
            "report": report_json(exc.report),
        }
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(service: Service) -> list[WorkspaceOut]:
    return [_out(w) for w in await service.resolve_list()]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: str, service: Service) -> object:
    try:
        return _out(await service.resolve_get(workspace_id))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkspaceOut)
async def create_workspace(
    body: WorkspaceCreate, request: Request, response: Response, service: Service
) -> object:
    data = WorkspaceInput(
        body.id, body.name, body.repo_url, body.git_secret_slug, body.security_service_id
    )
    try:
        workspace, existed = await service.resolve_create(
            request_author(request), data, body.verification_suffix
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu à l'identique : rien de créé, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(workspace)


@router.post("/{workspace_id}/access-check")
async def recheck_access(
    workspace_id: str, body: RecheckBody, request: Request, service: Service
) -> object:
    try:
        report = await service.resolve_recheck(
            request_author(request), workspace_id, body.verification_suffix
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return report_json(report)
