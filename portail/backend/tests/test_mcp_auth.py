from __future__ import annotations

from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from miles.apikeys.model import (
    KEY_RE,
    Access,
    Grant,
    KeyPrincipal,
    key_digest,
    new_key,
    shown_prefix,
)
from miles.mcp_api.auth import PRINCIPAL_STATE, SERVICES_STATE, ApiKeyAuth, presented_key

KEY = "mlk_" + "k" * 43
PRINCIPAL = KeyPrincipal("a" * 32, "Gateway", (Grant("retrait", Access.READ),))


class FakeKeys:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def resolve_authenticate(self, raw: str) -> KeyPrincipal | None:
        self.seen.append(raw)
        return PRINCIPAL if raw == KEY else None


def _headers(**values: str) -> dict[bytes, bytes]:
    return {k.replace("_", "-").lower().encode(): v.encode() for k, v in values.items()}


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Authorization": f"Bearer {KEY}"}, KEY),
        ({"Authorization": f"bearer   {KEY}  "}, KEY),
        ({"X_API_Key": KEY}, KEY),
        ({"Authorization": f"Bearer {KEY}", "X_API_Key": KEY}, KEY),
        ({"Authorization": f"Bearer {KEY}", "X_API_Key": "mlk_autre"}, None),
        ({"Authorization": f"Basic {KEY}"}, None),
        ({"Authorization": "Bearer "}, None),
        ({}, None),
    ],
)
def test_presented_key_accepts_bearer_or_header_and_refuses_ambiguity(
    headers: dict[str, str], expected: str | None
) -> None:
    assert presented_key(_headers(**headers)) == expected


def test_new_keys_are_random_well_formed_and_shown_by_prefix_only() -> None:
    first, second = new_key(), new_key()

    assert first != second and KEY_RE.match(first) and KEY_RE.match(second)
    assert shown_prefix(first) == first[:12] and len(key_digest(first)) == 32


def test_principal_rights_are_per_workspace_and_closed_elsewhere() -> None:
    principal = KeyPrincipal(
        "a" * 32, "x", (Grant("retrait", Access.READ), Grant("caisse", Access.WRITE))
    )

    assert (principal.can_read("retrait"), principal.can_write("retrait")) == (True, False)
    assert (principal.can_read("caisse"), principal.can_write("caisse")) == (True, True)
    assert (principal.can_read("stock"), principal.access_to("stock")) == (False, None)


async def _echo(request: Request) -> JSONResponse:
    principal: KeyPrincipal = getattr(request.state, PRINCIPAL_STATE)
    services: Any = getattr(request.state, SERVICES_STATE)
    return JSONResponse({"key": principal.key_id, "has_services": services is not None})


def _app(keys: FakeKeys) -> Starlette:
    app = Starlette(routes=[Mount("/mcp", app=ApiKeyAuth(Starlette(routes=[Route("/", _echo)])))])
    app.state.api_keys = keys
    return app


async def test_guard_lets_an_active_key_through_with_its_principal() -> None:
    keys = FakeKeys()
    transport = httpx.ASGITransport(app=_app(keys))
    async with httpx.AsyncClient(transport=transport, base_url="http://m") as client:
        passed = await client.get("/mcp/", headers={"X-API-Key": KEY})

    assert passed.json() == {"key": PRINCIPAL.key_id, "has_services": True}


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "mlk_inconnue"}, {"Authorization": f"Basic {KEY}"}],
)
async def test_guard_refuses_every_failure_alike_without_echoing_the_key(
    headers: dict[str, str],
) -> None:
    keys = FakeKeys()
    transport = httpx.ASGITransport(app=_app(keys))
    async with httpx.AsyncClient(transport=transport, base_url="http://m") as client:
        refused = await client.get("/mcp/", headers=headers)

    assert (refused.status_code, refused.json()) == (401, {"detail": "cle_requise"})
    assert refused.headers["www-authenticate"] == 'Bearer realm="miles-mcp"'
    # Un en-tête mal formé ne va même pas jusqu'à la base.
    assert keys.seen == (["mlk_inconnue"] if headers.get("X-API-Key") else [])


async def test_guard_never_reads_a_key_from_the_url() -> None:
    keys = FakeKeys()
    transport = httpx.ASGITransport(app=_app(keys))
    async with httpx.AsyncClient(transport=transport, base_url="http://m") as client:
        refused = await client.get(f"/mcp/?api_key={KEY}")

    assert refused.status_code == 401 and keys.seen == []
