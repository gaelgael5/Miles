from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.git.worktree import NonConformTreeError, diagnosis_json
from miles.workshop.trads import TradsFileError
from miles.workspaces.cultures import DefaultCultureIncompleteError
from miles.workspaces.model import (
    AccessCheckFailedError,
    RepositoryUnavailableError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceHeldError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
    report_json,
)
from miles.workspaces.service import WorkspacesService

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
    # Absents tant que le dépôt n'est pas paramétré : l'écran le signale au lieu
    # d'échouer à l'usage.
    repo_url: str | None
    git_connection_id: str | None
    security_service_id: str | None
    last_check: dict[str, Any] | None
    last_check_at: datetime | None
    created_at: datetime
    work_branch: str | None


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom seul (21/10/2026) ; l'identifiant est proposé par l'écran à partir du nom.
    id: str
    name: str
    # Obligatoire (story 639c25da, critère 1) : c'est la culture dont la valeur sera
    # exigée sur chaque clé du référentiel de traductions, donc le workspace ne peut pas
    # exister sans. Elle n'a rien à voir avec les cultures actives de l'application.
    default_culture: str


class RepositoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    git_connection_id: str
    repo_url: str
    # Choisi par l'écran, pour afficher le nom de la branche de vérification PENDANT
    # l'essai, pas seulement en cas d'échec.
    verification_suffix: str


class SecurityServiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_service_id: str | None


class WorkBranchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # Reprendre une branche homonyme déjà au dépôt. Faux par défaut : la première demande
    # ne touche jamais une branche existante, c'est l'écran qui fait confirmer puis rejoue.
    adopt_existing: bool = False


class RecheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_suffix: str


def _out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=w.id,
        name=w.name,
        repo_url=w.repo_url,
        git_connection_id=w.git_connection_id,
        security_service_id=w.security_service_id,
        last_check=w.last_check,
        last_check_at=w.last_check_at,
        created_at=w.created_at,
        work_branch=w.work_branch,
    )


def _replayed(response: Response, existed: bool) -> None:
    if existed:
        # Rejeu à l'identique : rien de modifié, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


# Table des refus du workspace, partagée par ses routeurs (dont celui de ses cultures) :
# une seule traduction, pour que deux écrans ne lisent pas deux formes du même refus.
REFUSALS = (
    DefaultCultureIncompleteError,
    NonConformTreeError,
    TradsFileError,
    RepositoryUnavailableError,
    WorkspaceInputError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    AccessCheckFailedError,
)


def refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, NonConformTreeError):
        detail = {"code": "arborescence_non_conforme", **diagnosis_json(exc.diagnosis)}
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(exc, RepositoryUnavailableError):
        detail = {"code": "acces_depot", "reason": exc.reason}
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(exc, WorkspaceInputError):
        invalid: dict[str, str] = {"field": exc.field}
        if exc.reason is not None:
            invalid["reason"] = exc.reason
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, invalid)
    if isinstance(exc, AccessCheckFailedError):
        failed = exc.report.failed()
        detail = {
            "code": "acces_insuffisant",
            "right": failed.right.value if failed else None,
            "reason": failed.reason.value if failed and failed.reason else None,
            "report": report_json(exc.report),
        }
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(exc, TradsFileError):
        # Une incohérence du dépôt se DIT, elle ne se compte pas comme un travail à faire :
        # la lire comme « rien ne manque » accepterait un changement de culture par défaut
        # à tort. On nomme le fichier, seul moyen pour l'humain de le corriger.
        detail = {"code": "trads_illisible", "path": exc.path, "reason": exc.reason}
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if isinstance(exc, DefaultCultureIncompleteError):
        # Le NOMBRE de clés manquantes, pas seulement le refus : l'écran mène à la liste
        # (critère 6), et sans le compte il ne peut pas dire l'ampleur du travail.
        detail = {"code": exc.code, "culture": exc.culture, "missing": exc.missing}
        return _error(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, WorkspaceHeldError):
        # Nommer le porteur : sans lui, l'écran ne peut dire à qui s'adresser.
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code, "by": exc.holder})
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
    except REFUSALS as exc:
        return refusal(exc)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(workspace_id: str, request: Request, service: Service) -> Response:
    """Miles oublie le workspace ; le dépôt git et ses branches restent intacts."""
    try:
        await service.resolve_delete(request_author(request), workspace_id)
    except REFUSALS as exc:
        return refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkspaceOut)
async def create_workspace(
    body: WorkspaceCreate, request: Request, response: Response, service: Service
) -> object:
    try:
        workspace, existed = await service.resolve_create(
            request_author(request), body.id, body.name, body.default_culture
        )
    except REFUSALS as exc:
        return refusal(exc)
    _replayed(response, existed)
    return _out(workspace)


@router.put("/{workspace_id}/repository", response_model=WorkspaceOut)
async def set_repository(
    workspace_id: str, body: RepositoryBody, request: Request, response: Response, service: Service
) -> object:
    try:
        workspace, existed = await service.resolve_set_repository(
            request_author(request),
            workspace_id,
            body.git_connection_id,
            body.repo_url,
            body.verification_suffix,
        )
    except REFUSALS as exc:
        return refusal(exc)
    _replayed(response, existed)
    return _out(workspace)


@router.put("/{workspace_id}/security-service", response_model=WorkspaceOut)
async def set_security_service(
    workspace_id: str, body: SecurityServiceBody, request: Request, service: Service
) -> object:
    try:
        workspace = await service.resolve_set_security_service(
            request_author(request), workspace_id, body.security_service_id
        )
    except REFUSALS as exc:
        return refusal(exc)
    return _out(workspace)


@router.post("/{workspace_id}/access-check")
async def recheck_access(
    workspace_id: str, body: RecheckBody, request: Request, service: Service
) -> object:
    try:
        report = await service.resolve_recheck(
            request_author(request), workspace_id, body.verification_suffix
        )
    except REFUSALS as exc:
        return refusal(exc)
    return report_json(report)


@router.post("/{workspace_id}/work-branch", status_code=status.HTTP_201_CREATED)
async def open_work_branch(
    workspace_id: str, body: WorkBranchBody, request: Request, response: Response, service: Service
) -> object:
    try:
        workspace, outcome = await service.resolve_open_work_branch(
            request_author(request), workspace_id, body.name, adopt_existing=body.adopt_existing
        )
    except REFUSALS as exc:
        return refusal(exc)
    if outcome is None:
        # Rejeu : ni seconde branche ni second commit (critère 9).
        response.status_code = status.HTTP_200_OK
    return {"workspace": _out(workspace).model_dump(mode="json"), "outcome": outcome}
