from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.datamodels.service import (
    DataModelsService,
    ModelEntry,
    ModelInUseError,
    ModelNotFoundError,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit de lecture seule viendra avec les rôles (1b282b07).
router = APIRouter(prefix="/api/workspaces/{workspace_id}/data-models")


def data_models_service(request: Request) -> DataModelsService:
    service: DataModelsService = request.app.state.data_models
    return service


Service = Annotated[DataModelsService, Depends(data_models_service)]


class ModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # « shared » pour un modèle transverse, sinon le nom du domaine.
    scope: str
    name: str
    path: str


class ModelContentOut(ModelOut):
    # Le YAML tel qu'il est dans le dépôt, octet pour octet.
    content: str


class ModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    # Le nom du modèle et donc du fichier se lit dans le document (`nom`).
    content: str


def _out(entry: ModelEntry) -> ModelOut:
    return ModelOut(scope=entry.scope, name=entry.name, path=entry.path)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    ModelSyntaxError,
    ModelGrammarError,
    ModelNotFoundError,
    ModelInUseError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ModelSyntaxError):
        detail = {"code": "yaml_invalide", "message": exc.message}
        return _error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ModelGrammarError):
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return _error(unprocessable, {"code": "modele_non_conforme", "problems": problems})
    if isinstance(exc, ModelInUseError):
        return _error(status.HTTP_409_CONFLICT, {"code": "utilise", "by": exc.users})
    if isinstance(exc, ModelNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "modele_inconnu")
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


@router.get("", response_model=list[ModelOut])
async def list_models(workspace_id: str, service: Service, branch: str | None = None) -> object:
    try:
        return [_out(e) for e in await service.resolve_list(workspace_id, branch=branch)]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{scope}/{name}", response_model=ModelContentOut)
async def get_model(
    workspace_id: str, scope: str, name: str, service: Service, branch: str | None = None
) -> object:
    try:
        entry, content = await service.resolve_get(workspace_id, scope, name, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return ModelContentOut(scope=entry.scope, name=entry.name, path=entry.path, content=content)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ModelOut)
async def create_model(
    workspace_id: str,
    body: ModelCreate,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, existed = await service.resolve_create(
            request_author(request), workspace_id, body.scope, body.content, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu à l'identique : ni fichier ni commit de plus, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(entry)


@router.delete("/{scope}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    workspace_id: str,
    scope: str,
    name: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> Response:
    try:
        await service.resolve_delete(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
