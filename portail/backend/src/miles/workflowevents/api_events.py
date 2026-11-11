from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.datamodels.grammar import MAX_TEXT_BYTES, ModelGrammarError, ModelSyntaxError
from miles.workflowevents.layout import EventEntry
from miles.workflowevents.schema import socle_fields
from miles.workflowevents.service import EventNotFoundError, WorkflowEventsService
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


class EventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # « shared » pour un événement transverse, sinon le nom du domaine.
    scope: str
    name: str
    path: str
    # Le `title` du schéma ; absent s'il n'en porte pas.
    label: str | None
    # Tenue par le système : 1 à la création, +1 à chaque enregistrement qui le change.
    version: int | None


class EventContentOut(EventOut):
    # Le YAML tel qu'il est dans le dépôt, octet pour octet.
    content: str


class EventDeclare(BaseModel):
    """Déclaration par libellé et nom : le YAML s'écrit ensuite à l'édition."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    label: str
    slug: str


class EventReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class SocleFieldOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: str
    # Posée par le moteur à l'intégration : une valeur de l'émetteur est ignorée.
    read_only: bool


def _out(entry: EventEntry) -> EventOut:
    return EventOut(
        scope=entry.scope,
        name=entry.name,
        path=entry.path,
        label=entry.label,
        version=entry.version,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    ModelSyntaxError,
    ModelGrammarError,
    EventNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ModelSyntaxError):
        detail = {"code": "yaml_invalide", "message": exc.message}
        return _error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ModelGrammarError):
        # Tout manquement qui arrive ici vient d'un événement (`EventGrammarError`, qui en
        # est une sous-classe) : c'est le même nom que rend la surface MCP, et c'est voulu.
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return _error(unprocessable, {"code": "evenement_non_conforme", "problems": problems})
    if isinstance(exc, EventNotFoundError):
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


@router.get("", response_model=list[EventOut])
async def list_events(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return [
            _out(e)
            for e in await service.resolve_list(
                request_author(request), workspace_id, branch=branch
            )
        ]
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/socle", response_model=list[SocleFieldOut])
async def socle(workspace_id: str) -> object:
    """Le socle commun que le moteur valide EN PLUS du schéma métier.

    Servi par le portail plutôt qu'écrit dans le front : la liste est celle du moteur
    installé, et deux recopies auraient divergé à la première montée de version.
    """
    return [
        SocleFieldOut(name=nom, type=type_declare, read_only=lecture_seule)
        for nom, type_declare, lecture_seule in socle_fields()
    ]


@router.get("/{scope}/{name}", response_model=EventContentOut)
async def get_event(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, content = await service.resolve_get(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return EventContentOut(**_out(entry).model_dump(), content=content)


@router.post("/declarations", status_code=status.HTTP_201_CREATED, response_model=EventOut)
async def declare_event(
    workspace_id: str,
    request: Request,
    body: EventDeclare,
    service: Service,
    response: Response,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_declare(
            request_author(request),
            workspace_id,
            body.scope,
            body.label,
            body.slug,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    # Rejeu à l'identique : rien n'a été écrit, donc 200 et non 201.
    if commit is None:
        response.status_code = status.HTTP_200_OK
    return _out(entry)


@router.put("/{scope}/{name}", response_model=EventOut)
async def replace_event(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    body: Annotated[EventReplace, Field()],
    service: Service,
    branch: str | None = None,
) -> object:
    if len(body.content.encode("utf-8")) > MAX_TEXT_BYTES:
        return _error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, {"code": "trop_grand", "max": MAX_TEXT_BYTES}
        )
    try:
        entry, _ = await service.resolve_replace(
            request_author(request), workspace_id, scope, name, body.content, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return _out(entry)


@router.delete("/{scope}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
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
