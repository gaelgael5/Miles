from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from miles.auth.context import AuthContext, auth_context, client_origin
from miles.oidc.api_connectors import oidc_service
from miles.oidc.service import ATTEMPT_TTL, CALLBACK_PATH, LoginError, OidcService

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth/oidc")
Service = Annotated[OidcService, Depends(oidc_service)]
Ctx = Annotated[AuthContext, Depends(auth_context)]

STATE_COOKIE = "miles_oidc_state"
# Destination fixe après la connexion : jamais une adresse reçue en paramètre, qui
# ferait du portail un tremplin vers un site tiers une fois l'utilisateur authentifié.
HOME = "/"


class PublicConnector(BaseModel):
    """Ce que l'écran de connexion voit d'un connecteur : de quoi afficher un bouton."""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str


def _home_with_error(error: LoginError) -> RedirectResponse:
    query = {"login_error": error.code}
    if error.connector_id is not None:
        query["connector"] = error.connector_id
    return RedirectResponse(f"{HOME}?{urlencode(query)}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/connectors", response_model=list[PublicConnector])
async def list_active_connectors(
    service: Service, culture: Annotated[str | None, Query(max_length=35)] = None
) -> list[PublicConnector]:
    connectors = await service.resolve_public_list(culture)
    return [PublicConnector(id=connector_id, label=label) for connector_id, label in connectors]


@router.get("/start")
async def start_login(
    request: Request, service: Service, ctx: Ctx, connector: Annotated[str, Query(max_length=63)]
) -> RedirectResponse:
    try:
        start = await service.resolve_start_login(connector)
    except LoginError as exc:
        log.warning(
            "oidc_depart_refuse", code=exc.code, reason=exc.reason, origin=client_origin(request)
        )
        return _home_with_error(exc)
    response = RedirectResponse(start.url, status_code=status.HTTP_303_SEE_OTHER)
    # SameSite=Lax et non Strict : le retour du fournisseur est une navigation venue
    # d'un autre site, sur laquelle un cookie Strict ne serait pas envoyé. Le cookie ne
    # vit que sur le chemin de retour et le temps de la tentative.
    response.set_cookie(
        STATE_COOKIE,
        start.state,
        max_age=int(ATTEMPT_TTL.total_seconds()),
        path=CALLBACK_PATH,
        httponly=True,
        secure=ctx.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/callback")
async def finish_login(
    request: Request,
    service: Service,
    ctx: Ctx,
    state: Annotated[str | None, Query(max_length=200)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    try:
        success = await service.resolve_finish_login(
            state, request.cookies.get(STATE_COOKIE), code, error
        )
    except LoginError as exc:
        # La cause va au journal, avec le connecteur ; l'écran ne reçoit qu'un code.
        log.warning(
            "oidc_connexion_refusee",
            code=exc.code,
            connector=exc.connector_id,
            reason=exc.reason,
            origin=client_origin(request),
        )
        response = _home_with_error(exc)
    else:
        response = RedirectResponse(HOME, status_code=status.HTTP_303_SEE_OTHER)
        identity = success.identity
        await ctx.resolve_open_oidc_session(
            response,
            success.connector_id,
            identity.subject,
            identity.display_name,
            identity.email,
            success.root_admin,
        )
    response.delete_cookie(
        STATE_COOKIE, path=CALLBACK_PATH, secure=ctx.cookie_secure, httponly=True
    )
    return response
