from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.auth.author import request_author
from miles.chains.layout import MAX_STEPS
from miles.chains.service import ChainNotFoundError, ChainsService, StoredChain, StoredStep
from miles.transform.api_transform import MAX_TEMPLATE_LENGTH, StepProblemOut, step_problem_out
from miles.transform.chain import ChainInvalidError
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/transformations")


def chains_service(request: Request) -> ChainsService:
    service: ChainsService = request.app.state.chains
    return service


Service = Annotated[ChainsService, Depends(chains_service)]


class StepIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    template: str = Field(max_length=MAX_TEMPLATE_LENGTH)
    target: str | None = Field(default=None, max_length=1024)


class ChainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    steps: list[StepIO] = Field(max_length=MAX_STEPS)


class ChainOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    steps: list[StepIO]


class ChainSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    # None : enchaînement illisible (retouché hors de Miles) ; la validation dit pourquoi.
    label: str | None
    steps: int | None


def _out(chain: StoredChain) -> ChainOut:
    steps = [StepIO(name=s.name, template=s.template, target=s.target) for s in chain.steps]
    return ChainOut(slug=chain.slug, label=chain.label, steps=steps)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    ChainInvalidError,
    ChainNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ChainInvalidError):
        problems: list[StepProblemOut] = [step_problem_out(p) for p in exc.problems]
        detail = {"code": "chaine_invalide", "problems": [p.model_dump() for p in problems]}
        return _error(unprocessable, detail)
    if isinstance(exc, ChainNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "chaine_inconnue")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        invalid = {"field": exc.field} | ({"reason": exc.reason} if exc.reason else {})
        return _error(unprocessable, invalid)
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=list[ChainSummaryOut])
async def list_chains(workspace_id: str, service: Service, branch: str | None = None) -> object:
    try:
        found = await service.resolve_list(workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [
        ChainSummaryOut(slug=c, label=None, steps=None)
        if isinstance(c, str)
        else ChainSummaryOut(slug=c.slug, label=c.label, steps=len(c.steps))
        for c in found
    ]


@router.get("/{slug}", response_model=ChainOut)
async def get_chain(
    workspace_id: str, slug: str, service: Service, branch: str | None = None
) -> object:
    try:
        return _out(await service.resolve_get(workspace_id, slug, branch=branch))
    except _REFUSALS as exc:
        return _refusal(exc)


@router.put("/{slug}", response_model=ChainOut)
async def save_chain(
    workspace_id: str,
    slug: str,
    body: ChainIn,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    steps = [StoredStep(s.name, s.template, s.target) for s in body.steps]
    try:
        chain, existed = await service.resolve_save(
            request_author(request), workspace_id, slug, body.label, steps, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Même chaîne à l'identique : aucun commit, et la réponse le dit.
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(chain)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chain(
    workspace_id: str, slug: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        await service.resolve_delete(request_author(request), workspace_id, slug, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
