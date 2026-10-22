from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.apikeys.model import Access
from miles.auth.author import request_author
from miles.auth.context import AuthContext
from miles.auth.sessions import LOCAL_ADMIN_KIND, OIDC_KIND, Session
from miles.oauth.access import GrantNotFoundError, OAuthAccess
from miles.oauth.flow import AuthorizeRedirect, AuthorizeRefused, OAuthFlow
from miles.oauth.model import LOCAL_KIND, Person
from miles.workspaces.service import WorkspacesService

# Ouvertes à toute session, OIDC sans droit comprise : le consentement et la liste de ses
# autorisations ne touchent que la personne elle-même. Ce qu'elle peut déléguer, lui, se
# borne à ses propres droits, recalculés ici à chaque demande.
router = APIRouter()


class AuthorizeParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    response_type: str | None = Field(default=None, max_length=40)
    client_id: str | None = Field(default=None, max_length=80)
    redirect_uri: str | None = Field(default=None, max_length=300)
    code_challenge: str | None = Field(default=None, max_length=200)
    code_challenge_method: str | None = Field(default=None, max_length=20)
    state: str | None = Field(default=None, max_length=500)
    scope: str | None = Field(default=None, max_length=500)
    resource: str | None = Field(default=None, max_length=300)


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(max_length=63)
    access: Access


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params: AuthorizeParams
    decision: Literal["approve", "deny"]
    grants: list[GrantIn] = Field(default=[], max_length=200)


def _person(request: Request) -> Person:
    session: Session = request.state.session
    author = request_author(request)
    if session.subject_kind == LOCAL_ADMIN_KIND:
        ctx: AuthContext = request.app.state.auth
        email = ctx.store.account.email if ctx.store.account is not None else None
        return Person(author.directory, author.subject, LOCAL_KIND, email, session.subject)
    name = session.display_name or session.subject
    return Person(author.directory, author.subject, OIDC_KIND, session.email, name)


async def _allowed(request: Request) -> dict[str, Access]:
    """Ce que la personne peut déléguer : ses propres droits, rien de plus.

    Aujourd'hui, seul l'administrateur racine a des droits, sur tous les workspaces.
    """
    session: Session = request.state.session
    if not (session.subject_kind == LOCAL_ADMIN_KIND or session.root_admin):
        return {}
    workspaces: WorkspacesService = request.app.state.workspaces
    return {w.id: Access.WRITE for w in await workspaces.resolve_list()}


@router.post("/api/oauth/authorize/check")
async def check(params: AuthorizeParams, request: Request) -> JSONResponse:
    """Ce que l'écran de consentement montre ; ou le refus, à l'écran ou vers le client."""
    flow: OAuthFlow = request.app.state.oauth_flow
    try:
        asked = await flow.resolve_request(params.model_dump(exclude_none=True))
    except AuthorizeRefused as exc:
        return JSONResponse(status_code=400, content={"detail": exc.code})
    except AuthorizeRedirect as exc:
        return JSONResponse({"redirect": exc.url})
    workspaces: WorkspacesService = request.app.state.workspaces
    names = {w.id: w.name for w in await workspaces.resolve_list()}
    allowed = await _allowed(request)
    return JSONResponse(
        {
            "client": {"id": asked.client.id, "label": asked.client.label},
            "redirect_uri": asked.redirect_uri,
            "allowed": [
                {"workspace_id": w, "name": names.get(w, w), "access": a.value}
                for w, a in sorted(allowed.items())
            ],
        }
    )


@router.post("/api/oauth/authorize")
async def decide(body: DecisionIn, request: Request) -> JSONResponse:
    """Le consentement ou le refus : rend l'adresse où renvoyer le navigateur."""
    flow: OAuthFlow = request.app.state.oauth_flow
    try:
        asked = await flow.resolve_request(body.params.model_dump(exclude_none=True))
        if body.decision == "deny":
            return JSONResponse({"redirect": flow.deny(asked)})
        grants = {g.workspace_id: g.access for g in body.grants}
        if len(grants) != len(body.grants):
            return JSONResponse(status_code=422, content={"detail": "workspace_en_double"})
        url = await flow.resolve_approve(asked, _person(request), grants, await _allowed(request))
    except AuthorizeRefused as exc:
        return JSONResponse(status_code=400, content={"detail": exc.code})
    except AuthorizeRedirect as exc:
        return JSONResponse({"redirect": exc.url})
    return JSONResponse({"redirect": url})


@router.get("/api/auth/me/oauth-grants")
async def my_grants(request: Request) -> JSONResponse:
    access: OAuthAccess = request.app.state.oauth_access
    views = await access.resolve_list(request_author(request))
    return JSONResponse(
        [
            {
                "id": v.id,
                "client": v.client_label,
                "grants": v.grants,
                "created_at": v.created_at.isoformat(),
                "last_used_at": None if v.last_used_at is None else v.last_used_at.isoformat(),
            }
            for v in views
        ]
    )


@router.delete("/api/auth/me/oauth-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(grant_id: str, request: Request) -> Response:
    access: OAuthAccess = request.app.state.oauth_access
    try:
        await access.resolve_revoke(request_author(request), grant_id)
    except GrantNotFoundError:
        return JSONResponse(status_code=404, content={"detail": "autorisation_inconnue"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
