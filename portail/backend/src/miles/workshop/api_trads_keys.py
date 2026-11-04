from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.workshop.trads import TradsFileError
from miles.workshop.trads_keys import PAGE_MAX, Page, TradsKeysService
from miles.workshop.trads_keys_errors import (
    ConcurrentEditError,
    KeyUnknownError,
    SlugTakenError,
    UnknownCultureError,
)
from miles.workshop.trads_values import (
    EmptyDefaultError,
    Key,
    ReorderingError,
    SlugError,
    TradsInputError,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Les clés d'un contexte et leurs valeurs par culture (story 289c8d9f). Réservé à qui peut
# éditer le paramétrage, comme le reste de l'atelier.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/trads/{context}/keys")


def trads_keys_service(request: Request) -> TradsKeysService:
    service: TradsKeysService = request.app.state.trads_keys
    return service


Service = Annotated[TradsKeysService, Depends(trads_keys_service)]


class KeyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    # Seules les cultures qui portent une valeur. Une culture absente n'est pas traduite ;
    # elle n'apparaît jamais avec une chaîne vide, ce qui serait une valeur.
    values: dict[str, str]


class PageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[KeyOut]
    total: int


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    # `null` vide une valeur ; une culture absente de la mappe n'est PAS touchée, et son
    # fichier n'est pas réécrit. C'est ce qui rend le diff git lisible.
    values: dict[str, str | None]


class ValuesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str | None]


class RenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_slug: str


_REFUSALS = (
    TradsFileError,
    TradsInputError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, TradsFileError):
        return _error(unprocessable, {"code": "trads_illisible", "path": exc.path})
    if isinstance(exc, ReorderingError):
        # On NOMME les caractères trouvés : ils sont invisibles, et sans leurs noms la
        # personne voit sa valeur refusée sans rien pouvoir corriger (critère 12).
        return _error(unprocessable, {"code": "direction_forcee", "found": exc.found})
    if isinstance(exc, EmptyDefaultError):
        detail = {"code": "valeur_par_defaut_obligatoire", "culture": exc.culture}
        return _error(unprocessable, detail)
    if isinstance(exc, SlugError):
        return _error(unprocessable, {"field": "slug", "reason": "forme"})
    if isinstance(exc, TradsInputError):
        return _error(unprocessable, {"code": "valeur_refusee"})
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field, "reason": exc.reason})
    if isinstance(exc, SlugTakenError):
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code, "slug": exc.slug})
    if isinstance(exc, KeyUnknownError):
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code, "slug": exc.slug})
    if isinstance(exc, UnknownCultureError):
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code, "culture": exc.culture})
    if isinstance(exc, ConcurrentEditError):
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


def _key_out(key: Key) -> KeyOut:
    return KeyOut(slug=key.slug, values=dict(key.values))


def _page_out(page: Page) -> PageOut:
    return PageOut(keys=[_key_out(k) for k in page.keys], total=page.total)


@router.get("", response_model=PageOut)
async def list_keys(
    workspace_id: str,
    context: str,
    request: Request,
    service: Service,
    branch: str | None = None,
    search: str = "",
    # Les clés sans valeur dans cette culture, et rien d'autre : la liste de travail d'un
    # traducteur qui ouvre l'écran et choisit sa langue.
    untranslated: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_MAX, ge=1, le=PAGE_MAX),
) -> object:
    try:
        page = await service.resolve_page(
            request_author(request),
            workspace_id,
            context,
            branch=branch,
            search=search,
            untranslated=untranslated,
            offset=offset,
            limit=limit,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _page_out(page)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_key(
    workspace_id: str,
    context: str,
    body: KeyCreate,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        commit = await service.resolve_save(
            request_author(request),
            workspace_id,
            context,
            body.slug,
            body.values,
            branch=branch,
            creating=True,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return {"slug": body.slug, "commit": commit}


@router.put("/{slug}")
async def save_values(
    workspace_id: str,
    context: str,
    slug: str,
    body: ValuesBody,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        commit = await service.resolve_save(
            request_author(request),
            workspace_id,
            context,
            slug,
            body.values,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return {"slug": slug, "commit": commit}


@router.post("/{slug}/rename")
async def rename_key(
    workspace_id: str,
    context: str,
    slug: str,
    body: RenameBody,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Action DISTINCTE de l'édition : le slug est ce que le paramétrage référencera, et
    le produit ne sait pas encore retrouver ce qui pointe une clé."""
    try:
        commit = await service.resolve_rename(
            request_author(request), workspace_id, context, slug, body.new_slug, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return {"slug": body.new_slug, "commit": commit}


@router.delete("/{slug}")
async def delete_key(
    workspace_id: str,
    context: str,
    slug: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        commit = await service.resolve_delete(
            request_author(request), workspace_id, context, slug, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return {"slug": slug, "commit": commit}
