from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from enrolement.environments.model import (
    MAX_LABEL_LENGTH,
    MAX_SLUG_LENGTH,
    Environment,
    EnvironmentError,
    EnvironmentInputError,
    EnvironmentNotFoundError,
    EnvironmentPairedError,
    EnvironmentSlugTakenError,
)
from enrolement.environments.service import EnvironmentService

# Routes d'ADMINISTRATION : le portillon exige une session. Même niveau de droit que
# l'acceptation d'un appariement — déclarer un environnement, c'est décider où des devices
# pourront atterrir.
router = APIRouter(prefix="/api/environments")


class EnvironmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bornes GROSSIÈRES, volontairement plus larges que la règle : les vraies sont
    # appliquées par `validate_label` et `validate_slug`, qui refusent en NOMMANT le champ.
    # Laisser pydantic parler le premier rendrait « corps invalide » là où l'écran doit
    # dire lequel des deux champs est en cause (mesuré sur la machine le 28/10/2026).
    label: str = Field(max_length=MAX_LABEL_LENGTH * 4)
    slug: str = Field(max_length=MAX_SLUG_LENGTH * 4)


class EnvironmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # L'identifiant STABLE, celui que l'écran renvoie pour renommer ou supprimer : le slug
    # est renommable, s'en servir de clé ferait échouer l'action juste après un renommage.
    id: UUID
    slug: str
    label: str
    created_at: datetime
    updated_at: datetime
    # L'origine de la stack appariée, nulle tant qu'aucune ne l'est. Nul n'est pas une
    # anomalie : un environnement déclaré et pas encore apparié est l'état du premier jour.
    paired_base_url: str | None


def _service(request: Request) -> EnvironmentService:
    service: EnvironmentService = request.app.state.environments
    return service


def _out(environnement: Environment) -> EnvironmentOut:
    return EnvironmentOut(
        id=environnement.id,
        slug=environnement.slug,
        label=environnement.label,
        created_at=environnement.created_at,
        updated_at=environnement.updated_at,
        paired_base_url=environnement.paired_base_url,
    )


def _error(exc: EnvironmentError) -> JSONResponse:
    if isinstance(exc, EnvironmentInputError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, EnvironmentSlugTakenError):
        # 409 et non 422 : la saisie est bien formée, c'est l'état du référentiel qui la
        # refuse. Retaper un slug correct ne règle pas une collision, et l'écran doit le
        # dire autrement.
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": "slug_pris"})
    if isinstance(exc, EnvironmentPairedError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "environnement_apparie"}
        )
    if isinstance(exc, EnvironmentNotFoundError):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "absent"})
    raise exc


@router.get("", response_model=list[EnvironmentOut])
async def get_environments(request: Request) -> list[EnvironmentOut]:
    return [_out(item) for item in await _service(request).resolve_environments()]


@router.post("", response_model=EnvironmentOut, status_code=status.HTTP_201_CREATED)
async def post_environment(request: Request, body: EnvironmentIn) -> EnvironmentOut | JSONResponse:
    try:
        return _out(
            await _service(request).resolve_create(request_author(request), body.label, body.slug)
        )
    except EnvironmentError as exc:
        return _error(exc)


@router.put("/{environment_id}", response_model=EnvironmentOut)
async def put_environment(
    request: Request, environment_id: UUID, body: EnvironmentIn
) -> EnvironmentOut | JSONResponse:
    """Renomme. Le libellé et le slug voyagent ensemble : l'écran édite les deux à la fois."""
    try:
        return _out(
            await _service(request).resolve_rename(
                request_author(request), environment_id, body.label, body.slug
            )
        )
    except EnvironmentError as exc:
        return _error(exc)


@router.delete("/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(request: Request, environment_id: UUID) -> Response:
    """Annotée `Response` et non `None` : une route en 204 ne peut pas déclarer de corps,
    et un type de retour optionnel en fait déduire un à FastAPI, qui refuse de démarrer.
    """
    try:
        await _service(request).resolve_delete(request_author(request), environment_id)
    except EnvironmentError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
