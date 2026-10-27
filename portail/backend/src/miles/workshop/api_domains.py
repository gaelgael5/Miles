from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.workshop.domains_service import DomainsService
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas, comme les modèles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/domains")


def domains_service(request: Request) -> DomainsService:
    service: DomainsService = request.app.state.domains
    return service


Service = Annotated[DomainsService, Depends(domains_service)]


class DomainOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class DomainCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom du répertoire `domains/<name>/` : c'est aussi l'identifiant du domaine.
    name: str


_REFUSALS = (
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.get("", response_model=list[DomainOut])
async def list_domains(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        names = await service.resolve_list(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [DomainOut(name=n) for n in names]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DomainOut)
async def add_domain(
    workspace_id: str,
    body: DomainCreate,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        commit = await service.resolve_add(
            request_author(request), workspace_id, body.name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        # Déjà là : ni fichier ni commit de plus, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return DomainOut(name=body.name)
