from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.datamodels.layout import ModelEntry
from miles.datamodels.service import DataModelsService, ModelInUseError, ModelNotFoundError
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
    # Le `title` du schéma ; absent s'il n'en porte pas.
    label: str | None
    # Tenue par le système : 1 à la création, +1 à chaque enregistrement qui le change.
    version: int | None


class ModelContentOut(ModelOut):
    # Le YAML tel qu'il est dans le dépôt, octet pour octet.
    content: str


class ModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    # Le nom du fichier et de l'`$id` : un JSON Schema n'a pas de clé de nom.
    name: str
    content: str


class ModelDeclare(BaseModel):
    """Déclaration par label et slug (Gael, 23/10/2026) : le YAML s'écrit à l'édition."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    label: str
    slug: str


class ModelReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


def _out(entry: ModelEntry) -> ModelOut:
    return ModelOut(
        scope=entry.scope,
        name=entry.name,
        path=entry.path,
        label=entry.label,
        version=entry.version,
    )


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
async def list_models(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return [
            _out(e)
            for e in await service.resolve_list(
                request_author(request), workspace_id, branch=branch
            )
        ]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{scope}/{name}", response_model=ModelContentOut)
async def get_model(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, content = await service.resolve_get(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ModelContentOut(**_out(entry).model_dump(), content=content)


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
        entry, commit = await service.resolve_create(
            request_author(request),
            workspace_id,
            body.scope,
            body.name,
            body.content,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        # Rejeu à l'identique : ni fichier ni commit de plus, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(entry)


@router.post("/declarations", status_code=status.HTTP_201_CREATED, response_model=ModelOut)
async def declare_model(
    workspace_id: str,
    body: ModelDeclare,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_declare(
            request_author(request), workspace_id, body.scope, body.label, body.slug, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(entry)


@router.put("/{scope}/{name}", response_model=ModelOut)
async def replace_model(
    workspace_id: str,
    scope: str,
    name: str,
    body: ModelReplace,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_replace(
            request_author(request), workspace_id, scope, name, body.content, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        # Même contenu : ni écriture ni commit, et la réponse le dit.
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
