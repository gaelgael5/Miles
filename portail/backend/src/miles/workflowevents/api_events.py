from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.workflowevents.dsl import FragmentError
from miles.workflowevents.schema import socle_schema
from miles.workflowevents.service import (
    DeclaredType,
    EventTypeNotFoundError,
    WorkflowEventsService,
)
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# `workflow-events` et non `events` : `/api/events` est DÉJÀ le journal d'audit. Deux
# notions différentes porteraient le même mot dans deux URL voisines, et la confusion
# coûterait plus cher que la longueur du chemin (Gael, 11/11/2026).
#
# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Même régime que les modèles de données.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/workflow-events")


def workflow_events_service(request: Request) -> WorkflowEventsService:
    service: WorkflowEventsService = request.app.state.workflow_events
    return service


Service = Annotated[WorkflowEventsService, Depends(workflow_events_service)]


class EventTypeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # « shared » pour un périmètre transverse, sinon le nom du domaine.
    scope: str
    name: str
    label: str
    # Le modèle qui décrit le payload, désigné comme partout ailleurs : par son chemin.
    model: str
    model_scope: str
    model_name: str
    # Clés de l'anti-doublon, DANS L'ORDRE : le moteur en dérive un hash par
    # concaténation, donc deux ordres donnent deux anti-doublons.
    unique: list[str]
    # Le modèle désigné manque sur la branche : rendu, parce que c'est ce qui bloque
    # l'enregistrement d'une version, et le cacher ferait chercher ailleurs.
    model_missing: bool


class Declaration(BaseModel):
    """Déclaration d'un type d'event : son identité, le modèle de son payload, ses clés."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    label: str
    slug: str
    model_scope: str
    model_name: str
    unique: list[str] = []


class Redeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    model_scope: str
    model_name: str
    unique: list[str] = []


def _out(declared: DeclaredType) -> EventTypeOut:
    return EventTypeOut(
        scope=declared.scope,
        name=declared.name,
        label=declared.label,
        model=declared.model_path,
        model_scope=declared.model[0],
        model_name=declared.model[1],
        unique=list(declared.unique),
        model_missing=declared.model_missing,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    FragmentError,
    ModelSyntaxError,
    ModelGrammarError,
    EventTypeNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, FragmentError):
        # L'artefact du périmètre ne se relit pas — retouché hors de Miles, ou produit par
        # un autre outil. Les positions sont celles du moteur, pour que l'écran renvoie à
        # la ligne fautive plutôt qu'à « le fichier est invalide ».
        problems = [
            {"line": p.line, "column": p.column, "message": p.message} for p in exc.problems
        ]
        return _error(unprocessable, {"code": "artefact_illisible", "problems": problems})
    if isinstance(exc, ModelSyntaxError):
        detail = {"code": "yaml_invalide", "message": exc.message}
        return _error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ModelGrammarError):
        # Tout manquement qui arrive ici vient du modèle DÉSIGNÉ (`EventModelError`, qui
        # est une sous-classe) : c'est le même nom que rend la surface MCP, et c'est voulu.
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return _error(unprocessable, {"code": "declaration_non_conforme", "problems": problems})
    if isinstance(exc, EventTypeNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "evenement_inconnu")
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


@router.get("", response_model=list[EventTypeOut])
async def list_event_types(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return [
            _out(d)
            for d in await service.resolve_list(
                request_author(request), workspace_id, branch=branch
            )
        ]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/socle", response_model=None)
async def socle(workspace_id: str) -> dict[str, Any]:
    """Le socle commun que le moteur valide EN PLUS du modèle désigné, en JSON Schema.

    Servi par le portail plutôt qu'écrit dans le front : il est lu du moteur installé, et
    une recopie aurait divergé à la première montée de version. Rendu TEL QUEL plutôt
    qu'aplati, pour que l'écran le monte dans le même éditeur visuel que les champs
    métier — c'est ce qui fait voir qu'un event dérive de ce type. C'est aussi lui qui dit
    quelles propriétés une clé d'unicité peut nommer sans être dans le modèle.
    """
    return socle_schema()


@router.get("/{scope}/{name}", response_model=EventTypeOut)
async def get_event_type(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        return _out(
            await service.resolve_get(
                request_author(request), workspace_id, scope, name, branch=branch
            )
        )
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("/declarations", status_code=status.HTTP_201_CREATED, response_model=EventTypeOut)
async def declare_event_type(
    workspace_id: str,
    request: Request,
    body: Declaration,
    service: Service,
    response: Response,
    branch: str | None = None,
) -> object:
    try:
        declared, commit = await service.resolve_declare(
            request_author(request),
            workspace_id,
            body.scope,
            body.label,
            body.slug,
            (body.model_scope, body.model_name),
            body.unique,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    # Rejeu à l'identique : rien n'a été écrit, donc 200 et non 201.
    if commit is None:
        response.status_code = status.HTTP_200_OK
    return _out(declared)


@router.put("/{scope}/{name}", response_model=EventTypeOut)
async def replace_event_type(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    body: Redeclaration,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        declared, _ = await service.resolve_replace(
            request_author(request),
            workspace_id,
            scope,
            name,
            body.label,
            (body.model_scope, body.model_name),
            body.unique,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(declared)


@router.delete("/{scope}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_type(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    service: Service,
    branch: str | None = None,
) -> Response:
    try:
        await service.resolve_delete(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
