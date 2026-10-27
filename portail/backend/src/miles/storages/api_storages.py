from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.storages.layout import MAX_COLUMNS, Index, StorageDoc
from miles.storages.service import (
    Saved,
    StorageInUseError,
    StorageInvalidError,
    StorageNotFoundError,
    StoragesService,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/storages")


def storages_service(request: Request) -> StoragesService:
    service: StoragesService = request.app.state.storages
    return service


Service = Annotated[StoragesService, Depends(storages_service)]


class IndexIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    # Plafond répété ici pour refuser tôt ; la raison est dans la déclaration (MAX_COLUMNS).
    columns: list[str] = Field(default=[], max_length=MAX_COLUMNS)


class StorageIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    label: str = Field(max_length=200)
    model: str = Field(max_length=200)
    keys: list[str] = Field(max_length=20)
    indexes: list[IndexIO] = Field(default=[], max_length=100)


class SavedOut(StorageIO):
    # Vrai si le modèle ou les index ont changé : le prochain import réécrira tous les
    # objets et leur index.
    rewrite_announced: bool


class StorageSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # None : déclaration illisible (retouchée hors de Miles) ; la validation dit pourquoi.
    label: str | None
    model: str | None
    keys: list[str] | None


def _doc(body: StorageIO) -> StorageDoc:
    return StorageDoc(
        body.name.strip(),
        body.label.strip(),
        body.model.strip(),
        tuple(k.strip() for k in body.keys),
        tuple(Index(i.name.strip(), tuple(c.strip() for c in i.columns)) for i in body.indexes),
    )


def _io(doc: StorageDoc) -> StorageIO:
    return StorageIO(
        name=doc.name,
        label=doc.label,
        model=doc.model,
        keys=list(doc.keys),
        indexes=[IndexIO(name=i.name, columns=list(i.columns)) for i in doc.indexes],
    )


def _saved(saved: Saved, response: Response) -> SavedOut:
    if saved.existed:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return SavedOut(**_io(saved.doc).model_dump(), rewrite_announced=saved.rewrite_announced)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    StorageInUseError,
    StorageInvalidError,
    StorageNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, StorageInvalidError):
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return _error(unprocessable, {"code": "storage_invalide", "problems": problems})
    if isinstance(exc, StorageInUseError):
        return _error(status.HTTP_409_CONFLICT, {"code": "storage_utilise", "sources": exc.sources})
    if isinstance(exc, StorageNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "storage_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=list[StorageSummaryOut])
async def list_storages(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        found = await service.resolve_list(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [
        StorageSummaryOut(name=s, label=None, model=None, keys=None)
        if isinstance(s, str)
        else StorageSummaryOut(name=s.name, label=s.label, model=s.model, keys=list(s.keys))
        for s in found
    ]


@router.get("/{name}", response_model=StorageIO)
async def get_storage(
    workspace_id: str, request: Request, name: str, service: Service, branch: str | None = None
) -> object:
    try:
        return _io(
            await service.resolve_get(request_author(request), workspace_id, name, branch=branch)
        )
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SavedOut)
async def declare_storage(
    workspace_id: str,
    body: StorageIO,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        saved = await service.resolve_save(
            request_author(request), workspace_id, _doc(body), create=True, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _saved(saved, response)


@router.put("/{name}", response_model=SavedOut)
async def change_storage(
    workspace_id: str,
    name: str,
    body: StorageIO,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    if body.name.strip() != name:
        # Le nom est l'identité du storage : il ne se renomme pas par une modification.
        return _error(status.HTTP_409_CONFLICT, "nom_fige")
    try:
        saved = await service.resolve_save(
            request_author(request), workspace_id, _doc(body), create=False, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _saved(saved, response)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage(
    workspace_id: str, name: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        await service.resolve_delete(request_author(request), workspace_id, name, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
