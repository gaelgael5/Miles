from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from miles_socle.git.versions import SavedVersion
from pydantic import BaseModel, ConfigDict

from miles.datamodels.grammar import Problem
from miles.workshop.service import (
    InvalidConfigurationError,
    VersionNotFoundError,
    WorkshopService,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit d'écriture sur le workspace viendra avec les rôles.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/versions")


def workshop_service(request: Request) -> WorkshopService:
    service: WorkshopService = request.app.state.workshop
    return service


Service = Annotated[WorkshopService, Depends(workshop_service)]


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    label: str
    commit: str
    author: str
    saved_at: datetime
    # None : étiquette antérieure aux branches filles, comptée à la base.
    branch: str | None


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class RestoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nouveau commit de la branche de travail : un retour crée un état, il n'en efface pas.
    commit: str


def _out(v: SavedVersion) -> VersionOut:
    return VersionOut(
        number=v.number,
        label=v.label,
        commit=v.commit,
        author=v.author,
        saved_at=v.saved_at,
        branch=v.branch,
    )


def _problem(p: Problem) -> dict[str, str | None]:
    return {"path": p.path, "code": p.code, "detail": p.detail}


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    InvalidConfigurationError,
    VersionNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, InvalidConfigurationError):
        reports = [
            {"path": r.path, "problems": [_problem(p) for p in r.problems]} for r in exc.reports
        ]
        return _error(unprocessable, {"code": "parametrage_invalide", "reports": reports})
    if isinstance(exc, VersionNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "version_inconnue")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc


@router.get("", response_model=list[VersionOut])
async def list_versions(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return [
            _out(v)
            for v in await service.resolve_list(
                request_author(request), workspace_id, branch=branch
            )
        ]
    except _REFUSALS as exc:
        return _refusal(exc)


class ReportOut(BaseModel):
    """Les manquements d'un fichier, de la même forme que dans le refus d'enregistrement.

    La MÊME forme, et c'est voulu : l'écran les rend avec le même composant, qu'ils
    arrivent à l'ouverture ou dans le refus d'un clic. Deux formes auraient donné deux
    rendus, et l'un des deux aurait fini par dire les choses moins bien que l'autre.
    """

    model_config = ConfigDict(extra="forbid")
    path: str
    problems: list[dict[str, str | None]]


class FreezableOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    # Ce qui empêche, repris tel quel des refus de l'enregistrement : « publication_requise »,
    # « rien_a_figer » ou « parametrage_invalide ». None quand rien n'empêche.
    reason: str | None
    # Ce que la validation du paramétrage a trouvé, DÈS L'OUVERTURE de l'écran (Gael,
    # 01/11/2026). Rendus même quand la raison est autre : celui qui doit d'abord publier
    # a le droit de savoir que le figement échouera ensuite.
    reports: list[ReportOut]


@router.get("/freezable", response_model=FreezableOut)
async def freezable(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    """Peut-on enregistrer une version ici, et sinon qu'est-ce qui l'empêche ?

    L'écran s'en sert pour griser le bouton AVANT le clic, et depuis le 01/11/2026 pour
    AFFICHER ce qui ne passe pas les règles sans qu'on ait eu à essayer — « il faudrait
    que le message d'erreur arrive avant que j'aie envie de commiter » (Gael).

    Déclaré avant la route « /{number} » : sans cela, « freezable » serait lu comme un
    numéro de version.
    """
    try:
        bloque = await service.resolve_freezable(
            request_author(request), workspace_id, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return FreezableOut(
        ok=bloque.reason is None,
        reason=bloque.reason,
        reports=[
            ReportOut(path=r.path, problems=[_problem(p) for p in r.problems])
            for r in bloque.reports
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VersionOut)
async def save_version(
    workspace_id: str,
    body: VersionCreate,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        saved, existed = await service.resolve_save(
            request_author(request), workspace_id, body.label, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if existed:
        # Rejeu d'une version déjà enregistrée : rien de posé, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(saved)


@router.post("/{number}/restore", response_model=RestoreOut)
async def restore_version(
    workspace_id: str, number: int, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        commit = await service.resolve_restore(
            request_author(request), workspace_id, number, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return RestoreOut(commit=commit)
