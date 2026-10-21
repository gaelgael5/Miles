from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.contracts.openapi import (
    SUPPORTED,
    ContractInvalidError,
    ContractSyntaxError,
    ParsedContract,
    UnsupportedVersionError,
)
from miles.contracts.service import (
    ContractEntry,
    ContractNotFoundError,
    ContractsService,
    ContractTakenError,
)
from miles.workspaces.model import (
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/contracts")
NO_OPERATION = "aucune_operation"


def contracts_service(request: Request) -> ContractsService:
    service: ContractsService = request.app.state.contracts
    return service


Service = Annotated[ContractsService, Depends(contracts_service)]


class OperationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str
    path: str
    operation_id: str | None


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Proposé depuis le titre, modifiable dans le même geste de création seulement.
    slug: str
    title: str
    openapi: str
    operations: list[OperationOut]
    warnings: list[str]


class ContractOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    sens: str
    title: str
    operations: int
    # Licite mais probablement une erreur de dépôt : signalé, pas refusé (critère 7).
    warnings: list[str]


class ContractDetailOut(ContractOut):
    operation_list: list[OperationOut]


class ContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    # Pas de défaut : None se refuse en nommant le champ, comme une valeur hors liste.
    sens: str | None = None
    content: str


class ContractChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str | None = None
    sens: str | None = None


def _operations(parsed: ParsedContract) -> list[OperationOut]:
    return [
        OperationOut(method=o.method, path=o.path, operation_id=o.operation_id)
        for o in parsed.operations
    ]


def _warnings(count: int) -> list[str]:
    return [NO_OPERATION] if count == 0 else []


def _out(entry: ContractEntry) -> ContractOut:
    return ContractOut(
        slug=entry.slug,
        sens=entry.direction,
        title=entry.title,
        operations=entry.operations,
        warnings=_warnings(entry.operations),
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    ContractSyntaxError,
    ContractInvalidError,
    UnsupportedVersionError,
    ContractTakenError,
    ContractNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ContractSyntaxError):
        detail = {"code": "openapi_illisible", "message": exc.message}
        return _error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ContractInvalidError):
        problems = [{"path": p.path, "message": p.message} for p in exc.problems]
        return _error(unprocessable, {"code": "openapi_invalide", "problems": problems})
    if isinstance(exc, UnsupportedVersionError):
        unsupported: dict[str, object] = {"code": "version_non_prise_en_charge"}
        return _error(
            unprocessable, unsupported | {"found": exc.found, "accepted": sorted(SUPPORTED)}
        )
    if isinstance(exc, ContractTakenError):
        return _error(status.HTTP_409_CONFLICT, {"code": "slug_pris", "by": exc.occupant})
    if isinstance(exc, ContractNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "contrat_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        invalid = {"field": exc.field} | ({"reason": exc.reason} if exc.reason else {})
        return _error(unprocessable, invalid)
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.post("/preview", response_model=PreviewOut)
async def preview_contract(workspace_id: str, body: PreviewIn, service: Service) -> object:
    try:
        slug, parsed = service.resolve_preview(body.content)
    except _REFUSALS as exc:
        return _refusal(exc)
    operations = _operations(parsed)
    return PreviewOut(
        slug=slug,
        title=parsed.title,
        openapi=parsed.openapi,
        operations=operations,
        warnings=_warnings(len(operations)),
    )


@router.get("", response_model=list[ContractOut])
async def list_contracts(workspace_id: str, service: Service) -> object:
    try:
        return [_out(e) for e in await service.resolve_list(workspace_id)]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{slug}", response_model=ContractDetailOut)
async def get_contract(workspace_id: str, slug: str, service: Service) -> object:
    try:
        entry, parsed = await service.resolve_get(workspace_id, slug)
    except _REFUSALS as exc:
        return _refusal(exc)
    return ContractDetailOut(**_out(entry).model_dump(), operation_list=_operations(parsed))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContractOut)
async def import_contract(
    workspace_id: str, body: ContractCreate, request: Request, response: Response, service: Service
) -> object:
    try:
        entry, _, existed = await service.resolve_create(
            request_author(request), workspace_id, body.slug, body.sens or "", body.content
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu du même fichier sous le même slug : ni doublon ni commit, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(entry)


@router.patch("/{slug}")
async def change_contract(workspace_id: str, slug: str, body: ContractChange) -> JSONResponse:
    # Le slug est l'identifiant stable : aucun mécanisme de propagation derrière lui, donc
    # aucun renommage, même pour un administrateur (critère 3). Le changement de sens
    # n'est pas instruit : refusé et signalé. La route existe pour dire pourquoi.
    if body.slug is not None and body.slug != slug:
        return _error(status.HTTP_409_CONFLICT, "slug_fige")
    return _error(status.HTTP_409_CONFLICT, "sens_fige")
