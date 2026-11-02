"""Les routes de la page des clés d'API de cet environnement.

Réservées à l'administrateur, comme toute route que la passerelle d'authentification ne
liste pas : une clé d'ingestion n'ouvre JAMAIS ces routes — elle ne sait que déposer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from environnement.apikeys.model import ApiKeyInfo, KeyInputError, UnknownSourceError
from environnement.apikeys.service import ApiKeysService, KeyNotFoundError, KeyRevokedError

router = APIRouter(prefix="/api/api-keys")


def api_keys_service(request: Request) -> ApiKeysService:
    service: ApiKeysService = request.app.state.api_keys
    return service


Service = Annotated[ApiKeysService, Depends(api_keys_service)]


class GrantsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Les NOMS des sources que la clé ouvre. Au moins un : le service refuse une liste
    # vide, parce qu'une clé qui n'ouvre rien est un secret distribué sans usage.
    sources: list[str] = Field(max_length=200)


class IssueIn(GrantsIn):
    label: str = Field(max_length=200)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    prefix: str
    sources: list[str]
    # Les octrois que la version servie ne déclare plus. L'écran le dit ; rien n'est
    # réécrit — une version suivante peut ramener la source.
    missing_sources: list[str]
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    last_used_at: datetime | None


class IssuedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ApiKeyOut
    # Rendue cette seule fois : la stack n'en garde que l'empreinte, et aucune route ne
    # la restitue — y compris « pour la recopier ».
    secret: str


class SourcesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Ce que la version servie déclare : les seuls octrois possibles. L'écran ne propose
    # que ça, plutôt que de laisser découvrir le refus après la saisie.
    sources: list[str]


def _out(info: ApiKeyInfo) -> ApiKeyOut:
    return ApiKeyOut(
        id=info.id,
        label=info.label,
        prefix=info.prefix,
        sources=list(info.sources),
        missing_sources=list(info.missing_sources),
        created_at=info.created_at,
        created_by=info.created_by,
        revoked_at=info.revoked_at,
        last_used_at=info.last_used_at,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


_REFUSALS = (KeyNotFoundError, KeyRevokedError, UnknownSourceError, KeyInputError)


def _refusal(exc: Exception) -> JSONResponse:
    if isinstance(exc, KeyNotFoundError):
        return _error(status.HTTP_404_NOT_FOUND, "cle_inconnue")
    if isinstance(exc, KeyRevokedError):
        return _error(status.HTTP_409_CONFLICT, "cle_revoquee")
    if isinstance(exc, UnknownSourceError):
        # `declared` les nomme toutes : l'écran corrige sans rappeler une liste.
        detail = {
            "field": "sources",
            "reason": "source_inconnue",
            "source": exc.source,
            "declared": list(exc.declared),
        }
        return _error(422, detail)
    if isinstance(exc, KeyInputError):
        return _error(422, {"field": exc.field, "reason": exc.reason})
    # Inatteignable : `_REFUSALS` ne porte que les quatre refus traités au-dessus. On
    # relance plutôt que de rendre un 422 muet — un refus non traduit est un défaut, pas
    # une erreur de saisie, et il doit remonter tel quel.
    raise exc


@router.get("/sources", response_model=SourcesOut)
async def declared_sources(service: Service) -> object:
    return SourcesOut(sources=list(await service.resolve_declared_sources()))


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(service: Service) -> object:
    return [_out(info) for info in await service.resolve_list()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=IssuedOut)
async def issue_key(
    body: IssueIn, request: Request, response: Response, service: Service
) -> object:
    try:
        info, secret = await service.resolve_issue(
            request_author(request), body.label, tuple(body.sources)
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    # La réponse porte la clé en clair : aucun cache, ni navigateur ni intermédiaire.
    response.headers["Cache-Control"] = "no-store"
    return IssuedOut(key=_out(info), secret=secret)


@router.put("/{key_id}/grants", response_model=ApiKeyOut)
async def set_grants(key_id: str, body: GrantsIn, request: Request, service: Service) -> object:
    try:
        return _out(
            await service.resolve_set_grants(request_author(request), key_id, tuple(body.sources))
        )
    except _REFUSALS as exc:
        return _refusal(exc)


@router.post("/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(key_id: str, request: Request, response: Response, service: Service) -> object:
    try:
        info, already = await service.resolve_revoke(request_author(request), key_id)
    except _REFUSALS as exc:
        return _refusal(exc)
    if already:
        # Rejouer une révocation est sans effet, pas une erreur : l'en-tête le dit sans
        # faire échouer un appel légitime.
        response.headers["X-Miles-Already-Exists"] = "true"
    return _out(info)
