from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.accounts.layout import MODES, SERVED_MODES, Delivery
from miles.accounts.service import (
    AccountsService,
    DeliveryRefusedError,
    ReferenceState,
    StorageUnknownError,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à qui peut éditer le paramétrage — l'administrateur tant que les rôles
# n'existent pas, même régime que les storages.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/account-reference")


def accounts_service(request: Request) -> AccountsService:
    service: AccountsService = request.app.state.accounts
    return service


Service = Annotated[AccountsService, Depends(accounts_service)]


class ProblemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    code: str
    detail: str | None


class DeliveryIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Un des `MODES`. Validé par le service et non par un `Literal` ici : le refus doit
    # nommer les modes SERVIS, ce qu'une erreur de schéma pydantic ne sait pas faire.
    mode: str = Field(max_length=32)
    # Jpath d'une propriété du modèle du storage, choisi dans une liste et jamais saisi.
    field: str = Field(max_length=400)


class ReferenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None : aucune référence déclarée sur cette branche. Ce n'est pas une erreur, et
    # l'écran doit le dire autrement qu'un défaut (critère 6).
    storage: str | None
    # Le modèle du storage désigné, lu dans sa déclaration — jamais stocké dans le
    # fichier de référence, qui n'aurait aucun moyen de le voir changer.
    model: str | None
    # None : le stockage est désigné, l'envoi ne l'est pas encore. Pas une erreur.
    delivery: DeliveryIO | None
    problem: ProblemOut | None
    # Rendus à CHAQUE lecture plutôt que codés dans l'écran : le jour où un mode de plus
    # est branché, l'écran suit sans être retouché, et ne peut pas en proposer un que le
    # serveur refuserait.
    modes: list[str]
    served_modes: list[str]


class ReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storage: str = Field(max_length=63)
    # Omis : l'envoi est EFFACÉ. Ce PUT pose la référence entière ; fusionner avec
    # l'existant ferait qu'aucun appel ne saurait retirer un envoi.
    delivery: DeliveryIO | None = None


def _out(state: ReferenceState) -> ReferenceOut:
    problem = state.problem
    delivery = None if state.reference is None else state.reference.delivery
    return ReferenceOut(
        storage=None if state.reference is None else state.reference.storage,
        model=state.model,
        delivery=None if delivery is None else DeliveryIO(mode=delivery.mode, field=delivery.field),
        problem=None
        if problem is None
        else ProblemOut(path=problem.path, code=problem.code, detail=problem.detail),
        modes=list(MODES),
        served_modes=list(SERVED_MODES),
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    DeliveryRefusedError,
    StorageUnknownError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, DeliveryRefusedError):
        return _error(
            unprocessable,
            {
                "code": exc.problem.code,
                "path": exc.problem.path,
                "detail": exc.problem.detail,
                "modes": exc.modes,
                "servis": exc.served,
            },
        )
    if isinstance(exc, StorageUnknownError):
        return _error(
            unprocessable,
            {"code": "storage_inconnu", "storage": exc.storage, "existants": exc.known},
        )
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=ReferenceOut)
async def read_reference(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        state = await service.resolve_get(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(state)


@router.put("", response_model=ReferenceOut)
async def set_reference(
    workspace_id: str,
    body: ReferenceIn,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    """Désigne le stockage. PUT et non POST : une branche a UNE référence de compte."""
    try:
        saved = await service.resolve_save(
            request_author(request),
            workspace_id,
            body.storage,
            None
            if body.delivery is None
            else Delivery(body.delivery.mode.strip(), body.delivery.field.strip()),
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if saved.unchanged:
        # Rejeu à l'identique : aucun commit n'a été fait, et l'appelant doit pouvoir le
        # savoir sans comparer lui-même (critère 10).
        response.headers["X-Miles-Unchanged"] = "true"
    return _out(saved.state)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reference(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        removed = await service.resolve_remove(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    headers = {} if removed else {"X-Miles-Unchanged": "true"}
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
