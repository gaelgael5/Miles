from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.workflows.service import Listed, WorkflowNotFoundError, WorkflowsService
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

# Réservé à l'administrateur tant que les rôles n'existent pas.
#
# `workflows` et non `workflow-events` : les deux surfaces sont distinctes et le resteront.
# Un artefact de périmètre déclare des types d'event ; un workflow déclare un comportement
# et INCLUT des périmètres.
router = APIRouter(prefix="/api/workspaces/{workspace_id}/workflows")


def workflows_service(request: Request) -> WorkflowsService:
    service: WorkflowsService = request.app.state.workflows
    return service


Service = Annotated[WorkflowsService, Depends(workflows_service)]


class ProblemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Positionné comme le MOTEUR le positionne : l'écran montre la ligne fautive, et un
    # décalage d'une unité ferait désigner la ligne voisine.
    line: int
    column: int
    message: str


class WorkflowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    # None quand le script ne se relit pas : les `problems` disent alors pourquoi.
    label: str | None = None
    version: int | None = None
    includes: list[str] = []
    states: int = 0
    # Vide quand le script se relit. Jamais une exception : un script cassé doit se VOIR
    # dans la liste, c'est lui qui bloquera l'enregistrement d'une version.
    problems: list[ProblemOut] = []


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom devient le `NAME` du script ET le nom de son fichier. Les règles du DSL sont
    # vérifiées par le service, qui sait les nommer ; le plafond est ici pour refuser tôt.
    name: str = Field(max_length=63)
    label: str = Field(max_length=200)


class ContentOut(WorkflowOut):
    # Le TEXTE du script, tel qu'il est dans la branche. L'écran d'écriture part de là.
    content: str


def _out(listed: Listed) -> WorkflowOut:
    header = listed.header
    return WorkflowOut(
        name=listed.name,
        label=header.label if header else None,
        version=header.version if header else None,
        includes=list(header.includes) if header else [],
        states=header.states if header else 0,
        problems=[
            ProblemOut(line=p.line, column=p.column, message=p.message) for p in listed.problems
        ],
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (
    WorkflowNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def _refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, WorkflowNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "workflow_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return _error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return _error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return _error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    return _error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        found = await service.resolve_list(request_author(request), workspace_id, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return [_out(listed) for listed in found]


@router.get("/{name}", response_model=ContentOut)
async def get_workflow(
    workspace_id: str, request: Request, name: str, service: Service, branch: str | None = None
) -> object:
    try:
        listed, text = await service.resolve_get(
            request_author(request), workspace_id, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ContentOut(**_out(listed).model_dump(), content=text)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WorkflowOut)
async def create_workflow(
    workspace_id: str, body: CreateIn, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        header = await service.resolve_create(
            request_author(request),
            workspace_id,
            body.name.strip(),
            body.label.strip(),
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return WorkflowOut(name=header.name, label=header.label, version=header.version)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workspace_id: str, name: str, request: Request, service: Service, branch: str | None = None
) -> Response:
    try:
        await service.resolve_delete(request_author(request), workspace_id, name, branch=branch)
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
