from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.accounts.service import AccountsService, ReferenceState, StorageUnknownError
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à qui peut éditer le paramétrage — l'administrateur tant que les rôles
# n'existent pas, même régime que les storages.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/account-reference")


def accounts_service(request: Request) -> AccountsService:
    service: AccountsService = request.app.state.accounts
    return service


Service = Annotated[AccountsService, Depends(accounts_service)]


class ProblemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    code: str
    detail: str | None


class ReferenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None : aucune référence déclarée sur cette branche. Ce n'est pas une erreur, et
    # l'écran doit le dire autrement qu'un défaut (critère 6).
    storage: str | None
    # Le modèle du storage désigné, lu dans sa déclaration — jamais stocké dans le
    # fichier de référence, qui n'aurait aucun moyen de le voir changer.
    model: str | None
    problem: ProblemOut | None


class ReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storage: str = Field(max_length=63)


def _out(state: ReferenceState) -> ReferenceOut:
    problem = state.problem
    return ReferenceOut(
        storage=None if state.reference is None else state.reference.storage,
        model=state.model,
        problem=None
        if problem is None
        else ProblemOut(path=problem.path, code=problem.code, detail=problem.detail),
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    StorageUnknownError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, StorageUnknownError):
        return _error(
            unprocessable,
            {"code": "storage_inconnu", "storage": exc.storage, "existants": exc.known},
        )
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=ReferenceOut)
async def read_reference(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        state = await service.resolve_get(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(state)


@router.put("", response_model=ReferenceOut)
async def set_reference(
    workspace_id: str,
    body: ReferenceIn,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    """Désigne le stockage. PUT et non POST : une branche a UNE référence de compte."""
    try:
        saved = await service.resolve_save(
            request_author(request), workspace_id, body.storage, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if saved.unchanged:
        # Rejeu à l'identique : aucun commit n'a été fait, et l'appelant doit pouvoir le
        # savoir sans comparer lui-même (critère 10).
        response.headers["X-Miles-Unchanged"] = "true"
    return _out(saved.state)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reference(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        removed = await service.resolve_remove(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    headers = {} if removed else {"X-Miles-Unchanged": "true"}
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
