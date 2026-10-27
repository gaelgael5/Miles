from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.git.graph import DEFAULT_COMMITS, MAX_COMMITS
from miles.workshop.branches import BranchEntry, BranchesService, BranchTakenError
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/branches")
# Les branches que regarde la personne connectée, tous workspaces confondus : le menu
# en a besoin d'un coup pour libeller chaque workspace « nom (branche) ».
views_router = APIRouter(prefix="/api/branch-views")


def branches_service(request: Request) -> BranchesService:
    service: BranchesService = request.app.state.branches
    return service


Service = Annotated[BranchesService, Depends(branches_service)]


class BranchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    branch: str
    base: bool


class CommitOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha: str
    # Vide : le commit est à la frontière de ce qui a été lu, la voie s'arrête là.
    parents: list[str]
    author: str
    written_at: str
    subject: str
    refs: list[str]


class ViewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str


class BranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    slug: str


def _out(entry: BranchEntry) -> BranchOut:
    return BranchOut(slug=entry.slug, label=entry.label, branch=entry.branch, base=entry.base)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    BranchTakenError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, BranchTakenError):
        return _error(status.HTTP_409_CONFLICT, {"code": "slug_pris", "by": exc.occupant})
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        invalid = {"field": exc.field} | ({"reason": exc.reason} if exc.reason else {})
        return _error(unprocessable, invalid)
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.get("", response_model=list[BranchOut])
async def list_branches(workspace_id: str, service: Service) -> object:
    try:
        return [_out(b) for b in await service.resolve_list(workspace_id)]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=BranchOut)
async def create_branch(
    workspace_id: str, body: BranchCreate, request: Request, response: Response, service: Service
) -> object:
    try:
        entry, existed = await service.resolve_create(
            request_author(request), workspace_id, body.label, body.slug
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu de la même création : ni seconde branche ni erreur, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(entry)


@router.put("/view", response_model=BranchOut)
async def set_view(workspace_id: str, body: ViewIn, request: Request, service: Service) -> object:
    try:
        entry = await service.resolve_set_view(request_author(request), workspace_id, body.branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(entry)


@views_router.get("", response_model=dict[str, str])
async def list_views(request: Request, service: Service) -> object:
    return await service.resolve_views(request_author(request))


@router.get("/graph", response_model=list[CommitOut])
async def branch_graph(workspace_id: str, service: Service, limit: int = DEFAULT_COMMITS) -> object:
    """Le graphe des branches de ce workspace, du plus récent au plus ancien."""
    if limit < 1 or limit > MAX_COMMITS:
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"champ": "limit"})
    try:
        commits = await service.resolve_graph(workspace_id, limit)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [
        CommitOut(
            sha=c.sha,
            parents=list(c.parents),
            author=c.author,
            written_at=c.written_at,
            subject=c.subject,
            refs=list(c.refs),
        )
        for c in commits
    ]
