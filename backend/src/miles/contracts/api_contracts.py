from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.contracts.history import Comparison, compare
from miles.contracts.openapi import ParsedContract
from miles.contracts.refusals import REFUSALS as _REFUSALS
from miles.contracts.refusals import error as _error
from miles.contracts.refusals import refusal as _refusal
from miles.contracts.remote import RemoteContractError, RemoteContracts
from miles.contracts.service import Contract, ContractsService, ContractVersion

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/contracts")
NO_OPERATION = "aucune_operation"


def contracts_service(request: Request) -> ContractsService:
    service: ContractsService = request.app.state.contracts
    return service


Service = Annotated[ContractsService, Depends(contracts_service)]


def remote_contracts(request: Request) -> RemoteContracts:
    remote: RemoteContracts = request.app.state.remote_contracts
    return remote


Remote = Annotated[RemoteContracts, Depends(remote_contracts)]


class OperationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str
    path: str
    operation_id: str | None


class FetchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class FetchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    openapi: str
    operations: list[OperationOut]
    # Licite mais probablement le mauvais fichier : signalé, pas refusé.
    warnings: list[str]


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    # None : fichier retouché hors de Miles et devenu illisible.
    title: str | None
    operations: int
    warnings: list[str]
    # None : version déposée hors de Miles, sans date ni auteur connus.
    imported_at: datetime | None
    imported_by: str | None


class VersionOperationOut(OperationOut):
    # « nouvelle » : absente de la version précédente. None : déjà là, ou rien à comparer.
    change: str | None


class VersionDetailOut(VersionOut):
    operation_list: list[VersionOperationOut]
    # Version à laquelle celle-ci est comparée ; None pour la première.
    compared_with: int | None
    removed: list[OperationOut]


class ContractOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    sens: str
    versions: list[VersionOut]


class ContractDetailOut(ContractOut):
    versions: list[VersionDetailOut]  # type: ignore[assignment]


class ContractDeclare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    slug: str
    # Pas de défaut : None se refuse en nommant le champ, comme une valeur hors liste.
    sens: str | None = None


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class ContractChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str | None = None
    sens: str | None = None
    label: str | None = None


def _operations(parsed: ParsedContract | None) -> list[OperationOut]:
    operations = parsed.operations if parsed is not None else ()
    return [
        OperationOut(method=o.method, path=o.path, operation_id=o.operation_id) for o in operations
    ]


def _warnings(count: int) -> list[str]:
    return [NO_OPERATION] if count == 0 else []


def _versions(contract: Contract) -> list[VersionDetailOut]:
    details, previous = [], None
    for version in contract.versions:
        details.append(_version(contract, version, compare(previous, version.parsed)))
        previous = (version.number, version.parsed)
    return details


def _version(
    contract: Contract, version: ContractVersion, comparison: Comparison
) -> VersionDetailOut:
    operations = version.parsed.operations if version.parsed is not None else ()
    deposit = contract.meta.imported(version.number)
    return VersionDetailOut(
        number=version.number,
        title=version.parsed.title if version.parsed is not None else None,
        operations=len(operations),
        warnings=_warnings(len(operations)),
        imported_at=datetime.fromisoformat(deposit.imported_at) if deposit else None,
        imported_by=deposit.by if deposit else None,
        operation_list=[
            VersionOperationOut(
                method=o.method,
                path=o.path,
                operation_id=o.operation_id,
                change="nouvelle" if (o.method, o.path) in comparison.added else None,
            )
            for o in operations
        ],
        compared_with=comparison.previous,
        removed=[
            OperationOut(method=o.method, path=o.path, operation_id=o.operation_id)
            for o in comparison.removed
        ],
    )


def _out(contract: Contract) -> ContractOut:
    summary = {"operation_list", "compared_with", "removed"}
    versions = [VersionOut(**v.model_dump(exclude=summary)) for v in _versions(contract)]
    meta = contract.meta
    return ContractOut(slug=meta.slug, label=meta.label, sens=meta.direction, versions=versions)


@router.post("/preview", response_model=PreviewOut)
async def preview_contract(workspace_id: str, body: VersionIn, service: Service) -> object:
    try:
        parsed = service.resolve_preview(body.content)
    except _REFUSALS as exc:
        return _refusal(exc)
    operations = _operations(parsed)
    return PreviewOut(
        title=parsed.title,
        openapi=parsed.openapi,
        operations=operations,
        warnings=_warnings(len(operations)),
    )


@router.post("/fetch", response_model=FetchOut)
async def fetch_contract(workspace_id: str, body: FetchIn, remote: Remote) -> object:
    # Lecture seule : le texte revient à l'écran et suit ensuite le chemin d'un fichier
    # chargé (aperçu, puis intégration), si bien que ce qui est versionné est ce qui a été vu.
    try:
        return FetchOut(content=await remote.resolve_fetch(body.url))
    except RemoteContractError as exc:
        reading: dict[str, object] = {"code": "lecture_distante", "reason": exc.reason}
        if exc.status is not None:
            reading["status"] = exc.status
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, reading)


@router.get("", response_model=list[ContractOut])
async def list_contracts(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return [
            _out(c)
            for c in await service.resolve_list(
                request_author(request), workspace_id, branch=branch
            )
        ]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{slug}", response_model=ContractDetailOut)
async def get_contract(
    workspace_id: str, request: Request, slug: str, service: Service, branch: str | None = None
) -> object:
    try:
        contract = await service.resolve_get(
            request_author(request), workspace_id, slug, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    versions = _versions(contract)
    return ContractDetailOut(**_out(contract).model_dump(exclude={"versions"}), versions=versions)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContractOut)
async def declare_contract(
    workspace_id: str,
    body: ContractDeclare,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        contract, existed = await service.resolve_declare(
            request_author(request),
            workspace_id,
            body.label,
            body.slug,
            body.sens or "",
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu de la même déclaration : ni doublon ni commit, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(contract)


@router.post(
    "/{slug}/versions", status_code=status.HTTP_201_CREATED, response_model=VersionDetailOut
)
async def import_version(
    workspace_id: str,
    slug: str,
    body: VersionIn,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        contract, number, existed = await service.resolve_import(
            request_author(request), workspace_id, slug, body.content, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Fichier déjà intégré à l'identique : la version existante, sans nouveau commit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return next(v for v in _versions(contract) if v.number == number)


@router.patch("/{slug}")
async def change_contract(workspace_id: str, slug: str, body: ContractChange) -> JSONResponse:
    # Le slug est l'identifiant stable : aucun mécanisme de propagation derrière lui, donc
    # aucun renommage, même pour un administrateur. Le changement de sens ou de label
    # n'est pas instruit : refusé et signalé. La route existe pour dire pourquoi.
    if body.slug is not None and body.slug != slug:
        return _error(status.HTTP_409_CONFLICT, "slug_fige")
    if body.label is not None:
        return _error(status.HTTP_409_CONFLICT, "label_fige")
    return _error(status.HTTP_409_CONFLICT, "sens_fige")
