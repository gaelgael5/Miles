from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, model_validator

from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.datamodels.layout import model_path
from miles.workflowevents.dsl import FragmentError
from miles.workflowevents.reading import DeclaredType, Perimeter
from miles.workflowevents.schema import socle_schema
from miles.workflowevents.service import EventTypeNotFoundError, WorkflowEventsService
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
    # Les modèles dont le payload HÉRITE (`allOf: $ref`), par leur CHEMIN — comme un
    # modèle se désigne partout ailleurs. Vide : l'event ne tient que du socle commun,
    # c'est-à-dire qu'il dérive de l'event de base.
    #
    # Le chemin plutôt qu'un couple (portée, nom) : l'écran compare alors ce chemin au
    # `model` des autres types pour dire DE QUEL EVENT l'héritage vient, sans avoir à
    # recomposer une clef.
    parents: list[str]


class ProblemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: int
    column: int
    message: str


class PerimeterOut(BaseModel):
    """Un périmètre et son artefact, pour l'arbre du bloc Events (story 8a9ff6bc)."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    # Le fichier de l'artefact, qu'il existe ou non : c'est lui que l'écran nomme quand il
    # ne se relit pas, et un périmètre sans aucun type n'en a pas encore.
    path: str
    types: list[EventTypeOut]
    # Ce qui empêche de relire CE périmètre. Non vide : `types` est vide, et ce n'est pas
    # « aucun type » — l'écran dit les deux choses différemment (critères 5 et 6).
    problems: list[ProblemOut]


class Declaration(BaseModel):
    """Déclaration d'un type d'event : son identité, ses clés, et D'OÙ VIENT son payload.

    Deux provenances, et une seule à la fois, parce que ce sont deux gestes différents :

    - un **modèle existant** que la déclaration DÉSIGNE. C'est le geste d'un agent, qui a
      écrit son modèle d'abord ;
    - un **parent** dont le payload hérite, le modèle étant alors créé avec l'event. C'est
      le geste de l'écran depuis le 19/11/2026 (Gael : « dans le menu types d'events ce
      que l'on fait c'est ajouter et créer les events »), et sans parent c'est l'event de
      base — le moteur applique sa racine d'office, donc aucun `$ref` n'est écrit.

    Une seule route pour les deux, parce que la chose déclarée est la même. Les mélanger
    dans un seul corps serait en revanche ambigu : `_la_provenance_est_unique` refuse.
    """

    model_config = ConfigDict(extra="forbid")
    scope: str
    label: str
    slug: str
    model_scope: str | None = None
    model_name: str | None = None
    parent_scope: str | None = None
    parent_name: str | None = None
    unique: list[str] = []

    @property
    def model(self) -> tuple[str, str] | None:
        return _pair(self.model_scope, self.model_name)

    @property
    def parent(self) -> tuple[str, str] | None:
        return _pair(self.parent_scope, self.parent_name)

    @model_validator(mode="after")
    def _la_provenance_est_unique(self) -> Declaration:
        """Une désignation à moitié écrite est refusée, et jamais prise pour autre chose.

        Sans ce refus, un `parent_name` envoyé sans sa portée créerait silencieusement un
        event dérivant du socle — l'écran dirait « hérite de l'event de base » là où la
        personne a choisi un parent. Et un corps portant les deux provenances écrirait un
        payload dont on ne saurait pas dire s'il hérite ou s'il désigne.
        """
        if (self.model_scope is None) != (self.model_name is None):
            raise ValueError("model")
        if (self.parent_scope is None) != (self.parent_name is None):
            raise ValueError("parent")
        if self.model is not None and self.parent is not None:
            raise ValueError("payload")
        return self


class Reparenting(BaseModel):
    """Vers quel type d'event rediriger l'héritage ; aucun : l'event de base."""

    model_config = ConfigDict(extra="forbid")
    parent_scope: str | None = None
    parent_name: str | None = None

    @property
    def parent(self) -> tuple[str, str] | None:
        return _pair(self.parent_scope, self.parent_name)

    @model_validator(mode="after")
    def _parent_is_whole(self) -> Reparenting:
        if (self.parent_scope is None) != (self.parent_name is None):
            raise ValueError("parent")
        return self


def _pair(scope: str | None, name: str | None) -> tuple[str, str] | None:
    return None if scope is None or name is None else (scope, name)


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
        parents=[model_path(*parent) for parent in declared.parents],
    )


def _perimeter(perimeter: Perimeter) -> PerimeterOut:
    return PerimeterOut(
        scope=perimeter.scope,
        path=perimeter.path,
        types=[_out(d) for d in perimeter.types],
        problems=[
            ProblemOut(line=p.line, column=p.column, message=p.message) for p in perimeter.problems
        ],
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


@router.get("", response_model=list[PerimeterOut])
async def list_perimeters(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    """Les périmètres de la branche, chacun avec ses types ou son artefact illisible.

    Par PÉRIMÈTRE et non en liste plate (story `8a9ff6bc`) : le bloc Events se déplie
    périmètre par périmètre, un périmètre sans aucun type doit s'y voir pour qu'on puisse
    y déclarer le premier, et un artefact retouché hors de Miles ne doit arrêter que le
    sien — l'écran nomme alors son fichier et garde le reste de l'arbre navigable.

    La liste plate existe encore, mais pour la surface MCP seule (`resolve_list`) : un
    agent ÉCRIT, et une liste amputée l'amènerait à déclarer par-dessus un périmètre qu'on
    n'a pas su relire. D'où le tout-ou-rien là-bas, et le détail ici.
    """
    try:
        return [
            _perimeter(p)
            for p in await service.resolve_perimeters(
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
    """Déclare un type d'event : sur un modèle existant, ou en créant son payload.

    Les deux gestes du corps (voir `Declaration`). Créer le payload écrit DEUX fichiers —
    le modèle et l'artefact — en un seul commit, et ne connaît pas le rejeu à l'identique :
    un nom déjà pris y est refusé, parce que le payload du type existant n'est pas celui
    que la demande décrit.
    """
    author = request_author(request)
    try:
        if body.model is not None:
            declared, commit = await service.resolve_declare(
                author,
                workspace_id,
                body.scope,
                body.label,
                body.slug,
                body.model,
                body.unique,
                branch=branch,
            )
        else:
            declared, commit = await service.resolve_create(
                author,
                workspace_id,
                body.scope,
                body.label,
                body.slug,
                body.parent,
                body.unique,
                branch=branch,
            )
    except _REFUSALS as exc:
        return _refusal(exc)
    # Rejeu à l'identique : rien n'a été écrit, donc 200 et non 201.
    if commit is None:
        response.status_code = status.HTTP_200_OK
    return _out(declared)


@router.put("/{scope}/{name}/parent", response_model=EventTypeOut)
async def redirect_inheritance(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    body: Reparenting,
    service: Service,
    branch: str | None = None,
) -> object:
    """Redirige l'héritage d'un type d'event ; un corps vide le ramène à l'event de base.

    `PUT` et non `PATCH` : l'héritage est une valeur unique, et on la remplace en entier.
    Route à part de la redéclaration parce que ce n'est pas l'artefact du périmètre qui
    change, c'est le modèle du payload — une seule ligne, son `allOf: $ref`.
    """
    try:
        declared, _ = await service.resolve_reparent(
            request_author(request), workspace_id, scope, name, body.parent, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
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
