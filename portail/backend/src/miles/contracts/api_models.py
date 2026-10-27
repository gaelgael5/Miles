from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from miles.auth.author import request_author
from miles.contracts.api_contracts import Service as Contracts
from miles.contracts.models_service import ContractModelsService
from miles.contracts.refusals import REFUSALS as _REFUSALS
from miles.contracts.refusals import refusal as _refusal
from miles.contracts.schemas import DerivedModelOut, VersionDetailOut, versions_out

# Modèles dérivés d'une version de contrat (story 47f55d8b) : lus et redérivés, jamais
# édités. Réservé à l'administrateur tant que les rôles n'existent pas, comme les contrats.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/contracts")


def contract_models_service(request: Request) -> ContractModelsService:
    service: ContractModelsService = request.app.state.contract_models
    return service


ModelsService = Annotated[ContractModelsService, Depends(contract_models_service)]


@router.post("/{slug}/versions/{number}/models", response_model=VersionDetailOut)
async def rederive_models(
    workspace_id: str,
    slug: str,
    number: int,
    request: Request,
    response: Response,
    service: ModelsService,
    contracts: Contracts,
    branch: str | None = None,
) -> object:
    """Réécrit les modèles dérivés d'une version d'après son fichier (story 47f55d8b)."""
    author = request_author(request)
    try:
        commit = await service.resolve_rederive(author, workspace_id, slug, number, branch=branch)
        contract = await contracts.resolve_get(author, workspace_id, slug, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        response.headers["X-Miles-Already-Exists"] = "true"
    return next(v for v in versions_out(contract) if v.number == number)


@router.get("/{slug}/versions/{number}/models/{name}", response_model=DerivedModelOut)
async def get_derived_model(
    workspace_id: str,
    slug: str,
    number: int,
    name: str,
    request: Request,
    service: ModelsService,
    branch: str | None = None,
) -> object:
    try:
        path, content = await service.resolve_model(
            request_author(request), workspace_id, slug, number, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return DerivedModelOut(name=name, path=path, content=content)
