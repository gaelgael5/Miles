from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.reference.labels import direction_of
from miles.workspaces.api_workspaces import REFUSALS, refusal, workspaces_service
from miles.workspaces.cultures import WorkspaceCultures
from miles.workspaces.cultures_service import WorkspaceCulturesService
from miles.workspaces.service import WorkspacesService

# Cultures du PARAMÉTRAGE d'un workspace, et non celles de l'application (`/api/cultures`,
# au socle) : les écrans de traduction lisent CELLES-CI. Routeur à part de celui des
# workspaces, qui atteignait sa limite de taille ; même préfixe, donc mêmes droits.
router = APIRouter(prefix="/api/workspaces")


def workspace_cultures_service(request: Request) -> WorkspaceCulturesService:
    service: WorkspaceCulturesService = request.app.state.workspace_cultures
    return service


Cultures = Annotated[WorkspaceCulturesService, Depends(workspace_cultures_service)]
Workspaces = Annotated[WorkspacesService, Depends(workspaces_service)]


class CultureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    culture: str


class CulturesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: str
    # Par code ; la culture par défaut est à part et vient toujours en premier (critère 2).
    additional: list[str]
    # Sens d'écriture de chaque culture, dérivé de CLDR (story 289c8d9f) : c'est le SERVEUR
    # qui le dit, pour que l'écran de saisie n'ait pas de table de langues à tenir — et
    # parce que le sens vient parfois du script et non de la langue (`az-Arab`).
    directions: dict[str, str]


def _out(cultures: WorkspaceCultures) -> CulturesOut:
    return CulturesOut(
        default=cultures.default,
        additional=list(cultures.additional),
        directions={code: direction_of(code) for code in cultures.all},
    )


@router.get("/{workspace_id}/cultures", response_model=CulturesOut)
async def get_cultures(workspace_id: str, workspaces: Workspaces, cultures: Cultures) -> object:
    try:
        # Le workspace d'abord : sans lui, un workspace inconnu rendrait le refus
        # « culture par défaut absente », qui ne désigne pas la cause.
        await workspaces.resolve_get(workspace_id)
        return _out(await cultures.resolve_cultures(workspace_id))
    except REFUSALS as exc:
        return refusal(exc)


@router.post("/{workspace_id}/cultures", response_model=CulturesOut)
async def add_culture(
    workspace_id: str,
    body: CultureBody,
    request: Request,
    workspaces: Workspaces,
    cultures: Cultures,
) -> object:
    try:
        await workspaces.resolve_get(workspace_id)
        result = await cultures.resolve_add(request_author(request), workspace_id, body.culture)
    except REFUSALS as exc:
        return refusal(exc)
    return _out(result)


@router.delete("/{workspace_id}/cultures/{culture}", response_model=CulturesOut)
async def remove_culture(
    workspace_id: str,
    culture: str,
    request: Request,
    workspaces: Workspaces,
    cultures: Cultures,
) -> object:
    """Retire une culture additionnelle ; ses fichiers restent dans le dépôt (critère 7)."""
    try:
        await workspaces.resolve_get(workspace_id)
        result = await cultures.resolve_remove(request_author(request), workspace_id, culture)
    except REFUSALS as exc:
        return refusal(exc)
    return _out(result)


@router.put("/{workspace_id}/cultures/default", response_model=CulturesOut)
async def set_default_culture(
    workspace_id: str,
    body: CultureBody,
    request: Request,
    workspaces: Workspaces,
    cultures: Cultures,
) -> object:
    try:
        await workspaces.resolve_get(workspace_id)
        result = await cultures.resolve_set_default(
            request_author(request), workspace_id, body.culture
        )
    except REFUSALS as exc:
        return refusal(exc)
    return _out(result)
