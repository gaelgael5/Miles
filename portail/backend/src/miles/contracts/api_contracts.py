from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from miles.auth.author import request_author
from miles.contracts.refusals import REFUSALS as _REFUSALS
from miles.contracts.refusals import error as _error
from miles.contracts.refusals import refusal as _refusal
from miles.contracts.remote import RemoteContractError, RemoteContracts
from miles.contracts.schemas import (
    ContractChange,
    ContractDeclare,
    ContractDetailOut,
    ContractOut,
    FetchIn,
    FetchOut,
    PreviewOut,
    VersionDetailOut,
    VersionIn,
    contract_out,
    operations_out,
    version_warnings,
    versions_out,
)
from miles.contracts.service import ContractsService

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/contracts")


def contracts_service(request: Request) -> ContractsService:
    service: ContractsService = request.app.state.contracts
    return service


Service = Annotated[ContractsService, Depends(contracts_service)]


def remote_contracts(request: Request) -> RemoteContracts:
    remote: RemoteContracts = request.app.state.remote_contracts
    return remote


Remote = Annotated[RemoteContracts, Depends(remote_contracts)]


@router.post("/preview", response_model=PreviewOut)
async def preview_contract(workspace_id: str, body: VersionIn, service: Service) -> object:
    try:
        parsed, models = service.resolve_preview(body.content)
    except _REFUSALS as exc:
        return _refusal(exc)
    operations = operations_out(parsed)
    return PreviewOut(
        title=parsed.title,
        openapi=parsed.openapi,
        operations=operations,
        warnings=version_warnings(len(operations)),
        models=models,
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
            contract_out(c)
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
    versions = versions_out(contract)
    return ContractDetailOut(
        **contract_out(contract).model_dump(exclude={"versions"}), versions=versions
    )


@router.get("/{slug}/versions/{number}/openapi")
async def contract_spec(
    workspace_id: str,
    slug: str,
    number: int,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Le document OpenAPI d'une version, pour le visualiseur Swagger.

    Rendu tel quel, sans modèle de réponse : le typer avec pydantic reviendrait à tenir
    une seconde définition d'OpenAPI dans Miles.
    """
    try:
        return await service.resolve_spec(
            request_author(request), workspace_id, slug, number, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)


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
    return contract_out(contract)


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
    return next(v for v in versions_out(contract) if v.number == number)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    workspace_id: str, slug: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        await service.resolve_delete(request_author(request), workspace_id, slug, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
