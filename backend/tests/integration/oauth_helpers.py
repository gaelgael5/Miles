from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from miles.oauth.flow import OAuthFlow
from tests.integration.portal_stack import PortalStack, utc_now

PUBLIC = "https://miles.exemple.invalid"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def open_oauth(portal: PortalStack) -> None:
    """Ouvre OAuth sur la pile de test, comme le fait MILES_PUBLIC_URL au démarrage."""
    state = portal.app.state
    state.public_url = PUBLIC
    state.oauth_flow = OAuthFlow(
        portal.pool, state.oauth_clients, state.oauth_clients.catalog, utc_now, PUBLIC + "/mcp/"
    )


@dataclass
class Pkce:
    verifier: str
    challenge: str


def new_pkce() -> Pkce:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return Pkce(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode())


async def declare_client(admin: httpx.AsyncClient, label: str = "claude.ai") -> str:
    created = await admin.post(
        "/api/oauth-clients", json={"label": label, "redirect_uris": [CALLBACK]}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def params(client_id: str, pkce: Pkce, **extra: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": "etat-42",
        "resource": PUBLIC + "/mcp/",
    } | extra


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def consent(
    person: httpx.AsyncClient, client_id: str, pkce: Pkce, grants: dict[str, str]
) -> httpx.Response:
    body = {
        "params": params(client_id, pkce),
        "decision": "approve",
        "grants": [{"workspace_id": w, "access": a} for w, a in grants.items()],
    }
    return await person.post("/api/oauth/authorize", json=body)


async def exchange(
    anonymous: httpx.AsyncClient, client_id: str, code: str, verifier: str
) -> httpx.Response:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "code_verifier": verifier,
    }
    return await anonymous.post("/oauth/token", data=form)


async def obtain_tokens(
    admin: httpx.AsyncClient, anonymous: httpx.AsyncClient, grants: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    """(client_id, réponse du jeton) : le parcours complet, comme claude.ai le joue."""
    client_id = await declare_client(admin)
    pkce = new_pkce()
    approved = await consent(admin, client_id, pkce, grants)
    code = query_of(approved.json()["redirect"])["code"]
    tokens = await exchange(anonymous, client_id, code, pkce.verifier)
    assert tokens.status_code == 200, tokens.text
    return client_id, tokens.json()
