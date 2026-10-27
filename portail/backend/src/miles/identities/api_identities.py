from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from miles.identities.forge_api import ForgeCheckError, UnsupportedForgeError
from miles.identities.service import (
    MAX_TOKEN_LENGTH,
    ConnectionNotFoundError,
    EmptyTokenError,
    GitIdentitiesService,
    GitIdentity,
    TokenInUseError,
)

# Ouvertes à toute session, OIDC sans droit comprise (préfixe OIDC_SESSION_PREFIXES de la
# passerelle) : chacun ne lit et n'écrit que sa propre identité, jamais celle d'un autre.
router = APIRouter(prefix="/api/auth/me/git-identities")


def identities_service(request: Request) -> GitIdentitiesService:
    service: GitIdentitiesService = request.app.state.git_identities
    return service


Service = Annotated[GitIdentitiesService, Depends(identities_service)]


class RepositoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    workspace_name: str
    can_write: bool | None


class AccountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str
    name: str
    email: str
    email_origin: str


class IdentityOut(BaseModel):
    """Ce que le profil montre d'une identité git : jamais le jeton lui-même."""

    model_config = ConfigDict(extra="forbid")
    connection_id: str
    connection_label: str
    base_url: str
    registered: bool
    account: AccountOut | None
    repositories: list[RepositoryOut]
    verified_at: datetime | None


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=MAX_TOKEN_LENGTH)


def _out(identity: GitIdentity) -> IdentityOut:
    account = identity.account
    return IdentityOut(
        connection_id=identity.connection_id,
        connection_label=identity.connection_label,
        base_url=identity.base_url,
        registered=account is not None,
        account=AccountOut(
            login=account.login,
            name=account.name,
            email=account.email,
            email_origin=account.email_origin.value,
        )
        if account is not None
        else None,
        repositories=[
            RepositoryOut(
                workspace_id=r.workspace_id, workspace_name=r.workspace_name, can_write=r.can_write
            )
            for r in identity.repositories
        ],
        verified_at=identity.verified_at,
    )


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("", response_model=list[IdentityOut])
async def list_identities(request: Request, service: Service) -> object:
    return [_out(i) for i in await service.resolve_list(request_author(request))]


@router.put("/{connection_id}", response_model=IdentityOut)
async def register_identity(
    connection_id: str, body: TokenIn, request: Request, service: Service
) -> object:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    try:
        identity = await service.resolve_register(
            request_author(request), connection_id, body.token
        )
    except EmptyTokenError:
        return _error(unprocessable, {"field": "token"})
    except ConnectionNotFoundError:
        return _error(status.HTTP_404_NOT_FOUND, "connexion_inconnue")
    except UnsupportedForgeError:
        return _error(unprocessable, {"code": "forge_non_prise_en_charge"})
    except ForgeCheckError as exc:
        return _error(unprocessable, {"code": "verification_impossible", "reason": exc.reason})
    return _out(identity)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_identity(connection_id: str, request: Request, service: Service) -> Response:
    try:
        await service.resolve_remove(request_author(request), connection_id)
    except TokenInUseError as exc:
        held = {"workspace_id": exc.workspace_id, "branch": exc.slug}
        return _error(status.HTTP_409_CONFLICT, {"code": "prise_de_main_en_cours"} | held)
    # Rejeu sans effet : retirer ce qui n'est plus là rend la même réponse.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
