from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.auth.author import request_author
from miles.auth.context import AuthContext
from miles.auth.sessions import Session
from miles.obo.service import ActorIdentitiesService, ActorInvalidError, ActorTakenError

# Personnelle, comme les préférences : ouverte à toute session (OIDC_SESSION_PATHS), elle
# n'atteint que la personne elle-même.
router = APIRouter(prefix="/api/auth/me/identity")


def actors_service(request: Request) -> ActorIdentitiesService:
    service: ActorIdentitiesService = request.app.state.actor_identities
    return service


Service = Annotated[ActorIdentitiesService, Depends(actors_service)]


class IdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None : aucun GUID posé ; les appels MCP faits par le portail en son nom restent
    # alors attribués à la clé de la gateway.
    actor: str | None


class IdentityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(max_length=200)


@router.get("", response_model=IdentityOut)
async def get_identity(request: Request, service: Service) -> IdentityOut:
    return IdentityOut(actor=await service.resolve_get(request_author(request)))


@router.put("", response_model=IdentityOut)
async def set_identity(body: IdentityIn, request: Request, service: Service) -> object:
    session: Session = request.state.session
    ctx: AuthContext = request.app.state.auth
    account = ctx.store.account
    # Nom et e-mail de la session, retenus pour signer les commits faits en son nom.
    email = session.email or (account.email if account is not None else None)
    try:
        await service.resolve_set(
            request_author(request), body.actor, session.display_name or session.subject, email
        )
    except ActorInvalidError:
        return JSONResponse(status_code=422, content={"detail": {"field": "actor"}})
    except ActorTakenError:
        return JSONResponse(status_code=409, content={"detail": "identite_prise"})
    return IdentityOut(actor=body.actor.strip())


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove_identity(request: Request, service: Service) -> Response:
    await service.resolve_remove(request_author(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
