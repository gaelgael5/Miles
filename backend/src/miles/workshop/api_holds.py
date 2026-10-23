from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.events.model import EventAuthor
from miles.workshop.holds import (
    AlreadyHoldingError,
    BranchHeldError,
    BranchHoldsService,
    HoldStatus,
)
from miles.workshop.holds_db import Hold
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas, comme les branches : la
# passerelle refuse toute autre session.
router = APIRouter(prefix="/api/workspaces/{workspace_id}")


def holds_service(request: Request) -> BranchHoldsService:
    service: BranchHoldsService = request.app.state.branch_holds
    return service


Service = Annotated[BranchHoldsService, Depends(holds_service)]


class HoldOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    # Qui la tient : nom et login de son compte de forge (critère 1).
    holder: str
    mine: bool
    taken_at: str


class StatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hold: HoldOut | None
    # Commits locaux non publiés, pour la seule personne qui a la main.
    unpublished: int | None


class PublishedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published: int


class ReleasedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    released: bool


def _hold(hold: Hold, person: EventAuthor) -> HoldOut:
    return HoldOut(
        slug=hold.slug,
        holder=hold.holder_label,
        mine=hold.held_by(person),
        taken_at=hold.taken_at.isoformat(),
    )


def _status(found: HoldStatus, person: EventAuthor) -> StatusOut:
    hold = None if found.hold is None else _hold(found.hold, person)
    return StatusOut(hold=hold, unpublished=found.unpublished)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (RepositoryUnavailableError, WorkspaceConflictError, WorkspaceNotFoundError)


def _refusal(exc: Exception) -> JSONResponse:
    conflict = status.HTTP_409_CONFLICT
    if isinstance(exc, BranchHeldError):
        return _error(conflict, {"code": exc.code, "by": exc.holder})
    if isinstance(exc, AlreadyHoldingError):
        held = {"workspace_id": exc.hold.workspace_id, "branch": exc.hold.slug}
        return _error(conflict, {"code": exc.code} | held)
    if isinstance(exc, WorkspaceConflictError):
        return _error(conflict, exc.code)
    if isinstance(exc, RepositoryUnavailableError):
        unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("/holds", response_model=list[HoldOut])
async def list_holds(workspace_id: str, request: Request, service: Service) -> object:
    person = request_author(request)
    holds = await service.resolve_holds(workspace_id)
    return [_hold(h, person) for h in holds.values()]


@router.get("/branches/{slug}/hold", response_model=StatusOut)
async def get_hold(workspace_id: str, slug: str, request: Request, service: Service) -> object:
    person = request_author(request)
    try:
        return _status(await service.resolve_status(person, workspace_id, slug), person)
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("/branches/{slug}/hold", status_code=status.HTTP_201_CREATED, response_model=HoldOut)
async def take_hold(
    workspace_id: str, slug: str, request: Request, response: Response, service: Service
) -> object:
    person = request_author(request)
    try:
        before = await service.resolve_holds(workspace_id)
        hold = await service.resolve_take(person, workspace_id, slug)
    except _REFUSALS as exc:
        return _refusal(exc)
    if slug in before:
        # Rejeu par la personne qui a déjà la main : ni seconde prise ni erreur.
        response.status_code = status.HTTP_200_OK
    return _hold(hold, person)


@router.post("/branches/{slug}/hold/publish", response_model=PublishedOut)
async def publish_hold(workspace_id: str, slug: str, request: Request, service: Service) -> object:
    try:
        count = await service.resolve_publish(request_author(request), workspace_id, slug)
    except _REFUSALS as exc:
        return _refusal(exc)
    return PublishedOut(published=count)


@router.delete("/branches/{slug}/hold", response_model=ReleasedOut)
async def release_hold(workspace_id: str, slug: str, request: Request, service: Service) -> object:
    try:
        released = await service.resolve_release(request_author(request), workspace_id, slug)
    except _REFUSALS as exc:
        return _refusal(exc)
    return ReleasedOut(released=released)
