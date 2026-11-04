from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.sources.layout import DEFAULT_WRITE_BATCH, Entry, EntryModes, SourceDoc
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


class ModesIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Un objet du modèle source, pour les intégrations à l'unité.
    element: bool = False
    # Un tableau d'objets du modèle source, MAX_BATCH au plus.
    batch: bool = False
    # Un fichier déposé, lu en flux selon le jpath de découpage.
    file: bool = False


class EntryIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=32)
    # Le modèle de ce qui arrive sur la méthode : il la type.
    source_model: str = Field(max_length=200)
    chain: str = Field(max_length=63)
    modes: ModesIO = ModesIO()
    # Requis par le seul mode fichier.
    split: str = Field(default="", max_length=1024)
    unified_transaction: bool = False
    # Lectures consécutives avant enregistrement ; au moins une, sinon rien n'est écrit.
    write_batch: int = Field(default=DEFAULT_WRITE_BATCH, ge=1)


class SourceIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=63)
    label: str = Field(max_length=200)
    # La donnée cible : le storage où les objets atterrissent.
    storage: str = Field(max_length=63)
    entries: list[EntryIO] = Field(default=[], max_length=50)


class SavedOut(SourceIO):
    # Vrai si une entrée a changé : le prochain import réécrira tous les objets.
    rewrite_announced: bool


class SourceSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # None : déclaration illisible (retouchée hors de Miles) ; la validation dit pourquoi.
    label: str | None
    storage: str | None
    # Nombre d'entrées déclarées ; None si la déclaration ne se lit pas.
    entries: int | None


def _doc(body: SourceIO) -> SourceDoc:
    return SourceDoc(
        body.name.strip(),
        body.label.strip(),
        body.storage.strip(),
        tuple(
            Entry(
                e.kind.strip(),
                e.source_model.strip(),
                e.chain.strip(),
                EntryModes(e.modes.element, e.modes.batch, e.modes.file),
                e.split.strip(),
                e.unified_transaction,
                e.write_batch,
            )
            for e in body.entries
        ),
    )


def _io(doc: SourceDoc) -> SourceIO:
    return SourceIO(
        name=doc.name,
        label=doc.label,
        storage=doc.storage,
        entries=[
            EntryIO(
                kind=e.kind,
                source_model=e.source_model,
                chain=e.chain,
                modes=ModesIO(element=e.modes.element, batch=e.modes.batch, file=e.modes.file),
                split=e.split,
                unified_transaction=e.unified_transaction,
                write_batch=e.write_batch,
            )
            for e in doc.entries
        ],
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
        SourceSummaryOut(name=s, label=None, storage=None, entries=None)
        if isinstance(s, str)
        else SourceSummaryOut(name=s.name, label=s.label, storage=s.storage, entries=len(s.entries))
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


@router.get("/{name}/openapi")
async def source_openapi(
    workspace_id: str, request: Request, name: str, service: Service, branch: str | None = None
) -> object:
    """Le document OpenAPI que cette source promet, dérivé de sa déclaration.

    Rendu tel quel, sans modèle de réponse : c'est un document OpenAPI, et le typer avec
    pydantic reviendrait à tenir une seconde définition d'OpenAPI dans Miles.
    """
    try:
        return await service.resolve_openapi(
            request_author(request), workspace_id, name, branch=branch
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
