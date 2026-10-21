from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.datamodels.grammar import Problem
from miles.git.versions import SavedVersion
from miles.workshop.service import (
    InvalidConfigurationError,
    VersionNotFoundError,
    WorkshopService,
)
from miles.workspaces.model import (
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/versions")


def workshop_service(request: Request) -> WorkshopService:
    service: WorkshopService = request.app.state.workshop
    return service


Service = Annotated[WorkshopService, Depends(workshop_service)]


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    label: str
    commit: str
    author: str
    saved_at: datetime


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class RestoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nouveau commit de la branche de travail : un retour crée un état, il n'en efface pas.
    commit: str


def _out(v: SavedVersion) -> VersionOut:
    return VersionOut(
        number=v.number, label=v.label, commit=v.commit, author=v.author, saved_at=v.saved_at
    )


def _problem(p: Problem) -> dict[str, str | None]:
    return {"path": p.path, "code": p.code, "detail": p.detail}


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    InvalidConfigurationError,
    VersionNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, InvalidConfigurationError):
        reports = [
            {"path": r.path, "problems": [_problem(p) for p in r.problems]} for r in exc.reports
        ]
        return _error(unprocessable, {"code": "parametrage_invalide", "reports": reports})
    if isinstance(exc, VersionNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "version_inconnue")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.get("", response_model=list[VersionOut])
async def list_versions(workspace_id: str, service: Service) -> object:
    try:
        return [_out(v) for v in await service.resolve_list(workspace_id)]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VersionOut)
async def save_version(
    workspace_id: str, body: VersionCreate, request: Request, response: Response, service: Service
) -> object:
    try:
        saved, existed = await service.resolve_save(
            request_author(request), workspace_id, body.label
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu d'une version déjà enregistrée : rien de posé, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(saved)


@router.post("/{number}/restore", response_model=RestoreOut)
async def restore_version(
    workspace_id: str, number: int, request: Request, service: Service
) -> object:
    try:
        commit = await service.resolve_restore(request_author(request), workspace_id, number)
    except _REFUSALS as exc:
        return _refusal(exc)
    return RestoreOut(commit=commit)
