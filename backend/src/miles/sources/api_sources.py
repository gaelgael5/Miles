from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.auth.author import request_author
from miles.sources.layout import Filterable, SourceDoc
from miles.sources.service import (
    Saved,
    SourceInvalidError,
    SourceNotFoundError,
    SourcesService,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/sources")


def sources_service(request: Request) -> SourcesService:
    service: SourcesService = request.app.state.sources
    return service


Service = Annotated[SourcesService, Depends(sources_service)]


class FilterableIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    jpath: str = Field(max_length=1024)


class SourceIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    model: str = Field(max_length=200)
    split: str = Field(max_length=1024)
    keys: list[str] = Field(max_length=20)
    chain: str = Field(max_length=63)
    large_file: bool = False
    unified_transaction: bool = False
    filterables: list[FilterableIO] = Field(default=[], max_length=100)


class SavedOut(SourceIO):
    # Vrai si la chaîne ou les propriétés filtrables ont changé : le prochain import
    # réécrira tous les objets et leur index.
    rewrite_announced: bool


class SourceSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # None : déclaration illisible (retouchée hors de Miles) ; la validation dit pourquoi.
    model: str | None
    chain: str | None


def _doc(body: SourceIO) -> SourceDoc:
    return SourceDoc(
        body.name.strip(),
        body.model.strip(),
        body.split.strip(),
        tuple(k.strip() for k in body.keys),
        body.chain.strip(),
        body.large_file,
        body.unified_transaction,
        tuple(Filterable(f.name.strip(), f.jpath.strip()) for f in body.filterables),
    )


def _io(doc: SourceDoc) -> SourceIO:
    return SourceIO(
        name=doc.name,
        model=doc.model,
        split=doc.split,
        keys=list(doc.keys),
        chain=doc.chain,
        large_file=doc.large_file,
        unified_transaction=doc.unified_transaction,
        filterables=[FilterableIO(name=f.name, jpath=f.jpath) for f in doc.filterables],
    )


def _saved(saved: Saved, response: Response) -> SavedOut:
    if saved.existed:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return SavedOut(**_io(saved.doc).model_dump(), rewrite_announced=saved.rewrite_announced)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    SourceInvalidError,
    SourceNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, SourceInvalidError):
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return _error(unprocessable, {"code": "source_invalide", "problems": problems})
    if isinstance(exc, SourceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "source_inconnue")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=list[SourceSummaryOut])
async def list_sources(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        found = await service.resolve_list(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [
        SourceSummaryOut(name=s, model=None, chain=None)
        if isinstance(s, str)
        else SourceSummaryOut(name=s.name, model=s.model, chain=s.chain)
        for s in found
    ]


@router.get("/{name}", response_model=SourceIO)
async def get_source(
    workspace_id: str, request: Request, name: str, service: Service, branch: str | None = None
) -> object:
    try:
        return _io(
            await service.resolve_get(request_author(request), workspace_id, name, branch=branch)
        )
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SavedOut)
async def declare_source(
    workspace_id: str,
    body: SourceIO,
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
async def change_source(
    workspace_id: str,
    name: str,
    body: SourceIO,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    if body.name.strip() != name:
        # Le nom est l'identité de la source : il ne se renomme pas par une modification.
        return _error(status.HTTP_409_CONFLICT, "nom_fige")
    try:
        saved = await service.resolve_save(
            request_author(request), workspace_id, _doc(body), create=False, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _saved(saved, response)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    workspace_id: str, name: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        await service.resolve_delete(request_author(request), workspace_id, name, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
