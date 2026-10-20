from __future__ import annotations

import asyncio
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.auth.admin_account import InvalidAdminInputError
from miles.auth.context import AuthContext, auth_context, client_origin
from miles.auth.env_file import EnvEntriesPresentError, EnvFileError
from miles.auth.passwords import MAX_PASSWORD_LENGTH, WeakPasswordError, verify_password
from miles.auth.sessions import OIDC_KIND, SESSION_COOKIE, Session, db_delete_session

log = structlog.get_logger(__name__)
router = APIRouter()
Ctx = Annotated[AuthContext, Depends(auth_context)]


class BootstrapStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_declared: bool


class BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    username: str = Field(max_length=64)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH + 1)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class Me(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["local_admin", "oidc"]
    username: str
    email: str | None
    # Connecteur OIDC de la session ; absent pour le compte d'amorçage.
    directory: str | None = None


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("/api/bootstrap/status", response_model=BootstrapStatus)
async def get_bootstrap_status(ctx: Ctx) -> BootstrapStatus:
    return BootstrapStatus(admin_declared=ctx.store.account is not None)


@router.post("/api/bootstrap", status_code=status.HTTP_201_CREATED, response_model=Me)
async def post_bootstrap(
    body: BootstrapRequest,
    request: Request,
    response: Response,
    ctx: Ctx,
) -> Me | JSONResponse:
    origin = client_origin(request)
    # Garde de sécurité : ce chemin crée un administrateur sans authentification,
    # il ne doit plus rien accepter dès qu'un compte existe.
    if ctx.store.account is not None:
        log.warning("amorcage_refuse_deja_fait", origin=origin)
        return _error(status.HTTP_409_CONFLICT, "amorcage_ferme")
    try:
        account = await ctx.store.resolve_declare(body.email, body.username, body.password)
    except InvalidAdminInputError as exc:
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": str(exc)})
    except WeakPasswordError as exc:
        return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, {"rule": exc.rule, "limit": exc.limit})
    except EnvEntriesPresentError:
        # Un amorçage concurrent a écrit le compte entre notre lecture et la sienne.
        log.warning("amorcage_refuse_concurrent", origin=origin)
        return _error(status.HTTP_409_CONFLICT, "amorcage_ferme")
    except EnvFileError as exc:
        log.error("amorcage_ecriture_impossible", origin=origin, reason=str(exc))
        return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "env_ecriture_impossible")
    await ctx.resolve_open_admin_session(response, account.username)
    log.info("amorcage_session_ouverte", username=account.username, origin=origin)
    return Me(kind="local_admin", username=account.username, email=account.email)


@router.post("/api/auth/login", response_model=Me)
async def post_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    ctx: Ctx,
) -> Me | JSONResponse:
    origin = client_origin(request)
    account = ctx.store.account
    if account is None:
        return _error(status.HTTP_403_FORBIDDEN, "amorcage_requis")
    if ctx.throttle.is_blocked(origin):
        log.warning("connexion_locale_freinee", origin=origin)
        return _error(status.HTTP_429_TOO_MANY_REQUESTS, "trop_de_tentatives")
    # On vérifie l'empreinte même si le nom ne correspond pas : la durée de réponse
    # ne doit pas dire lequel des deux est faux.
    password_ok = await asyncio.to_thread(
        verify_password, account.password_hash.get_secret_value(), body.password
    )
    if not (password_ok and body.username == account.username):
        ctx.throttle.record_failure(origin)
        log.warning("connexion_locale_refusee", origin=origin)
        return _error(status.HTTP_401_UNAUTHORIZED, "identifiants_invalides")
    await ctx.resolve_open_admin_session(response, account.username)
    log.info("connexion_locale_reussie", username=account.username, origin=origin)
    return Me(kind="local_admin", username=account.username, email=account.email)


@router.get("/api/auth/me", response_model=Me)
async def get_me(request: Request, ctx: Ctx) -> Me:
    session: Session = request.state.session
    if session.subject_kind == OIDC_KIND:
        # Le nom affiché est cosmétique : à défaut, on montre le sub, jamais rien.
        return Me(
            kind="oidc",
            username=session.display_name or session.subject,
            email=session.email,
            directory=session.directory,
        )
    account = ctx.store.account
    if account is None:
        # La passerelle refuse déjà toute session sans compte : arriver ici est un défaut.
        raise RuntimeError("route protégée atteinte sans compte d'amorçage")
    return Me(kind="local_admin", username=session.subject, email=account.email)


@router.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def post_logout(request: Request, ctx: Ctx) -> Response:
    session: Session = request.state.session
    await db_delete_session(ctx.db, session.digest)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=ctx.cookie_secure, httponly=True)
    return response
