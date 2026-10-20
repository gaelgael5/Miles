from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.author import request_author
from miles.cultures.service import (
    Culture,
    CulturesService,
    EmptyChangeError,
    FallbackCultureError,
    UnknownCulturesError,
)

# Les routes passent par la passerelle : seule une session ouvre /api/cultures. Seul
# le compte d'amorçage en ouvre une aujourd'hui ; quand les rôles arriveront, la
# gestion restera à l'administrateur et la lecture des actives à tout authentifié.
router = APIRouter(prefix="/api/cultures")


def cultures_service(request: Request) -> CulturesService:
    service: CulturesService = request.app.state.cultures
    return service


Service = Annotated[CulturesService, Depends(cultures_service)]


class CultureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    label_en: str
    label_native: str
    active: bool


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[str]
    active: bool


class ActivationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed: list[str]


def _out(culture: Culture) -> CultureOut:
    return CultureOut(
        code=culture.code,
        label_en=culture.label_en,
        label_native=culture.label_native,
        active=culture.active,
    )


def _error(detail: object) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": detail}
    )


@router.get("", response_model=list[CultureOut])
async def list_cultures(service: Service) -> list[CultureOut]:
    return [_out(c) for c in await service.resolve_list(only_active=False)]


@router.get("/active", response_model=list[CultureOut])
async def list_active_cultures(service: Service) -> list[CultureOut]:
    return [_out(c) for c in await service.resolve_list(only_active=True)]


@router.post("/activation", response_model=ActivationResult)
async def set_activation(
    body: ActivationRequest, request: Request, service: Service
) -> ActivationResult | JSONResponse:
    author = request_author(request)
    try:
        changed = await service.resolve_set_active(author, body.codes, body.active)
    except FallbackCultureError:
        return _error({"code": "repli_obligatoire"})
    except UnknownCulturesError as exc:
        return _error({"field": "codes", "unknown": list(exc.codes)})
    except EmptyChangeError:
        return _error({"field": "codes"})
    return ActivationResult(changed=changed)
