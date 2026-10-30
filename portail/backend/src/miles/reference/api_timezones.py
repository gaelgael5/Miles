from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from miles.reference.activation import EmptyChangeError, UnknownSlugsError
from miles.reference.model import Timezone, validate_culture
from miles.reference.timezones import TimezonesService

# Le référentiel des fuseaux horaires, section Global du portail. Le préfixe suit celui des
# pays — `/api/timezones` — et n'emploie pas le mot « référentiel », déjà pris par les
# référentiels d'objets ingérés, ceux de mapping dans git, et les storages.
router = APIRouter(prefix="/api/timezones")


def timezones_service(request: Request) -> TimezonesService:
    service: TimezonesService = request.app.state.timezones
    return service


Service = Annotated[TimezonesService, Depends(timezones_service)]


class TimezoneOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # L'identifiant IANA. Il sort TOUJOURS, et l'écran l'affiche à côté du libellé : CLDR
    # rend un nom de métazone — « heure d'Europe centrale » vaut pour Paris, Berlin et
    # Madrid —, donc le libellé seul ne désigne aucun fuseau.
    slug: str
    label: str
    # TOUS les pays, dans l'ordre d'IANA, par leur slug alpha-3. Jamais vide : la table
    # IANA donne au moins un pays à chacune de ses zones.
    countries: list[str]
    active: bool


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slugs: list[str]
    active: bool


class ActivationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed: list[str]


def _out(timezone: Timezone) -> TimezoneOut:
    return TimezoneOut(
        slug=timezone.slug,
        label=timezone.label,
        countries=list(timezone.countries),
        active=timezone.active,
    )


@router.get("", response_model=list[TimezoneOut])
async def list_timezones(
    service: Service,
    culture: Annotated[str | None, Query(max_length=40)] = None,
    only_active: bool = False,
    country: Annotated[str | None, Query(max_length=3)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[TimezoneOut]:
    """Les fuseaux, avec leur libellé dans la culture demandée et leurs pays.

    `country` est l'usage pour lequel le lien vers les pays existe : un écran qui a déjà le
    pays ne proposera que ses deux ou trois fuseaux au lieu de trois cents. Il filtre sur
    TOUS les pays d'un fuseau — filtrer sur le premier ne rendrait rien pour le Luxembourg,
    qui n'est le premier pays d'aucune zone.
    """
    fuseaux = await service.resolve_list(
        culture=validate_culture(culture),
        only_active=only_active,
        country=country,
        search=q,
    )
    return [_out(f) for f in fuseaux]


@router.post("/activation", response_model=ActivationResult)
async def set_activation(
    body: ActivationRequest, request: Request, service: Service
) -> ActivationResult | JSONResponse:
    """Active ou désactive exactement la sélection reçue. Rend ce qui a réellement changé."""
    try:
        changed = await service.resolve_set_active(request_author(request), body.slugs, body.active)
    except UnknownSlugsError as exc:
        return _error({"field": "slugs", "unknown": list(exc.slugs)})
    except EmptyChangeError:
        return _error({"field": "slugs"})
    return ActivationResult(changed=changed)


def _error(detail: object) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail}
    )
