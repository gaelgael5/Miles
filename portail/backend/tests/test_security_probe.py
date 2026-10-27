from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from miles_socle.secrets.model import Secret

from miles.security.probe import Outcome, probe_keycloak, realm_issuer

BASE = "https://security.example.org"
TOKEN = f"{BASE}/realms/miles/protocol/openid-connect/token"
DISCOVERY = f"{BASE}/realms/miles/.well-known/openid-configuration"
Handler = Callable[[httpx.Request], httpx.Response]


def _provider(discovery: httpx.Response, token: httpx.Response | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY:
            return discovery
        assert str(request.url) == TOKEN and token is not None
        return token

    return handler


async def _probe(handler: Handler) -> Outcome:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        return await probe_keycloak(http, BASE, "miles", "miles-bo", Secret("s3cr3t"), False)


FOUND = httpx.Response(200, json={"token_endpoint": TOKEN})


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (_provider(FOUND, httpx.Response(200, json={"access_token": "a"})), Outcome.OK),
        (_provider(httpx.Response(404)), Outcome.REALM_UNKNOWN),
        (
            _provider(FOUND, httpx.Response(401, json={"error": "unauthorized_client"})),
            Outcome.REFUSED,
        ),
        (_provider(FOUND, httpx.Response(400, json={"error": "invalid_client"})), Outcome.REFUSED),
        (_provider(httpx.Response(503)), Outcome.UNREACHABLE),
        (_provider(httpx.Response(200, text="pas du json")), Outcome.UNREACHABLE),
        (
            _provider(httpx.Response(200, json={"token_endpoint": "http://x/token"})),
            Outcome.UNREACHABLE,
        ),
        (_provider(FOUND, httpx.Response(500)), Outcome.UNREACHABLE),
    ],
)
async def test_probe_gives_one_of_four_distinct_diagnostics(
    handler: Handler, expected: Outcome
) -> None:
    assert await _probe(handler) is expected


async def test_network_failure_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    assert await _probe(handler) is Outcome.UNREACHABLE


async def test_probe_presents_the_client_credentials_in_basic_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY:
            return FOUND
        seen.append(request)
        return httpx.Response(200, json={})

    await _probe(handler)

    assert seen[0].headers["authorization"].startswith("Basic ")
    assert b"s3cr3t" not in seen[0].content
    assert b"grant_type=client_credentials" in seen[0].content


def test_realm_issuer_escapes_the_realm() -> None:
    assert realm_issuer(BASE + "/", "a b") == f"{BASE}/realms/a%20b"
