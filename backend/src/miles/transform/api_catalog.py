from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.events.model import EventAuthor
from miles.git.snapshot import CommitNotFoundError, snapshot
from miles.transform.catalog import app_floor, functions_catalog, models_catalog
from miles.transform.engine import function_registry
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Lecture seule, réservée à l'administrateur tant que les rôles n'existent pas.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/catalog")


@dataclass(frozen=True)
class CatalogService:
    """Ce qu'un template peut employer à une version donnée (story 28f00c74).

    Les fonctions viennent du registre que le moteur évalue, les modèles et le
    plancher d'application de la branche, lus à l'instant ou à un commit : rien n'est
    recopié, donc rien ne diverge.
    """

    branches: WorkBranches

    async def resolve(
        self, viewer: EventAuthor, workspace_id: str, branch: str | None, commit: str | None
    ) -> dict[str, Any]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            source = await snapshot(copy, commit) if commit else None
            paths = await (source.paths() if source else copy.paths())
            read = source.read if source else copy.read
            return {
                "commit": source.commit if source else copy.head,
                "app_floor": await app_floor(read),
                "models": await models_catalog(paths, read),
            }


def catalog_service(request: Request) -> CatalogService:
    service: CatalogService = request.app.state.template_catalog
    return service


Service = Annotated[CatalogService, Depends(catalog_service)]


class FunctionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    signature: str
    description: str
    documentation: str
    parameters: list[dict[str, Any]]
    returns: str | None
    # Faux : documentation incomplète, l'entrée n'est pas à employer en l'état.
    complete: bool
    missing: list[str]


class ModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    name: str
    path: str
    properties: list[dict[str, Any]] | None


class CatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commit: str
    # Plancher du manifest.json : la cible d'un template destiné au terminal.
    app_floor: str | None
    functions: list[FunctionOut]
    models: list[ModelOut]


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    CommitNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, CommitNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "commit_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "acces_depot", "reason": exc.reason}
        )
    if isinstance(exc, WorkspaceInputError):
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=CatalogOut)
async def get_catalog(
    workspace_id: str,
    request: Request,
    service: Service,
    branch: str | None = None,
    commit: str | None = None,
) -> object:
    try:
        found = await service.resolve(request_author(request), workspace_id, branch, commit)
    except _REFUSALS as exc:
        return _refusal(exc)
    functions = [
        FunctionOut(
            name=f.name,
            signature=f.signature,
            description=f.description,
            documentation=f.documentation,
            parameters=list(f.parameters),
            returns=f.returns,
            complete=not f.missing,
            missing=list(f.missing),
        )
        for f in functions_catalog(function_registry())
    ]
    models = [
        ModelOut(
            scope=m.scope,
            name=m.name,
            path=m.path,
            properties=list(m.properties) if m.properties is not None else None,
        )
        for m in found["models"]
    ]
    return CatalogOut(
        commit=found["commit"], app_floor=found["app_floor"], functions=functions, models=models
    )
