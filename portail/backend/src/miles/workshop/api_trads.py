from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.workshop.trads import Context, TradsFileError
from miles.workshop.trads_service import ContextTakenError, Removal, TradsService
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à qui peut éditer le paramétrage — l'administrateur tant que les rôles n'existent
# pas, comme les domaines et les modèles (story 623898d1, critère 10).
router = APIRouter(prefix="/api/workspaces/{workspace_id}/trads")


def trads_service(request: Request) -> TradsService:
    service: TradsService = request.app.state.trads
    return service


Service = Annotated[TradsService, Depends(trads_service)]


class ContextOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: str
    keys: int
    # Clés traduites par culture du workspace ; rapporté au total, c'est la couverture.
    translated: dict[str, int]
    # Cultures retirées du workspace dont le dépôt garde encore un fichier, et le nombre
    # de valeurs de chacune : sans ce compte, personne ne saurait qu'elles existent.
    obsolete: dict[str, int]


class ContextCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom du répertoire `trads/<name>/`, figé après création.
    name: str
    label: str


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class RemovalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: int
    values: int


_REFUSALS = (
    TradsFileError,
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
        # Une incohérence du dépôt se dit, et on nomme le fichier : sans son chemin,
        # personne ne peut aller le corriger.
        return _error(unprocessable, {"code": "trads_illisible", "path": exc.path})
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        detail = {"field": exc.field}
        if exc.reason is not None:
            detail["reason"] = exc.reason
        return _error(unprocessable, detail)
    if isinstance(exc, ContextTakenError):
        return _error(status.HTTP_409_CONFLICT, {"code": exc.code, "label": exc.label})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


def _out(context: Context) -> ContextOut:
    return ContextOut(
        name=context.name,
        label=context.label,
        keys=context.keys,
        translated=dict(context.translated),
        obsolete=dict(context.obsolete),
    )


def _removal_out(removal: Removal) -> RemovalOut:
    return RemovalOut(keys=removal.keys, values=removal.values)


@router.get("", response_model=list[ContextOut])
async def list_contexts(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        contexts = await service.resolve_list(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [_out(c) for c in contexts]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContextOut)
async def add_context(
    workspace_id: str,
    body: ContextCreate,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        await service.resolve_add(
            request_author(request), workspace_id, body.name, body.label, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ContextOut(name=body.name, label=body.label, keys=0, translated={}, obsolete={})


@router.put("/{name}", response_model=ContextOut)
async def relabel_context(
    workspace_id: str,
    name: str,
    body: LabelBody,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Change le LIBELLÉ. Il n'y a aucune route pour changer le nom technique : il entre
    dans le chemin sur disque et dans tout ce qui référencera ses clés."""
    try:
        await service.resolve_relabel(
            request_author(request), workspace_id, name, body.label, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ContextOut(name=name, label=body.label, keys=0, translated={}, obsolete={})


@router.get("/{name}/removal", response_model=RemovalOut)
async def preview_removal(
    workspace_id: str,
    name: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Ce que la suppression emporterait : la confirmation l'annonce (critère 6)."""
    try:
        removal = await service.resolve_removal(
            request_author(request), workspace_id, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _removal_out(removal)


@router.delete("/{name}", response_model=RemovalOut)
async def delete_context(
    workspace_id: str,
    name: str,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        _, removal = await service.resolve_delete(
            request_author(request), workspace_id, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    response.status_code = status.HTTP_200_OK
    return _removal_out(removal)


@router.delete("/{name}/obsolete/{culture}", response_model=RemovalOut)
async def delete_obsolete_culture(
    workspace_id: str,
    name: str,
    culture: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Retire le fichier d'une culture que le workspace ne retient plus.

    Le seul « obsolète » que le produit crée lui-même : un fichier gardé exprès au retrait
    d'une culture, et que rien ne permettait ensuite d'enlever.
    """
    try:
        _, values = await service.resolve_delete_obsolete(
            request_author(request), workspace_id, name, culture, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return RemovalOut(keys=0, values=values)
