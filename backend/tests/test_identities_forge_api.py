from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from miles.identities.forge_api import (
    EmailOrigin,
    ForgeCheckError,
    ForgeRefusal,
    UnsupportedForgeError,
    api_root,
    can_write,
    fetch_account,
)
from miles.secrets.model import Secret

ROOT = "https://api.github.com"
TOKEN = Secret("ghp_personnel")


def _http(routes: dict[str, httpx.Response]) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return routes.get(request.url.path, httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), seen


def test_api_root_follows_the_forge_of_the_connection() -> None:
    assert api_root("https://github.com/acme", ()) == ROOT
    assert api_root("http://gitea:3000", ("gitea:3000",)) == "http://gitea:3000/api/v1"
    with pytest.raises(UnsupportedForgeError):
        api_root("https://gitlab.com/acme", ())


async def test_public_email_and_name_are_those_of_the_account() -> None:
    user = {"login": "gael", "id": 7, "name": "Gaël", "email": "gael@acme.test"}
    http, seen = _http({"/user": httpx.Response(200, json=user)})

    account = await fetch_account(http, ROOT, TOKEN)

    assert (account.login, account.name, account.email) == ("gael", "Gaël", "gael@acme.test")
    assert account.email_origin is EmailOrigin.PUBLIC
    assert seen[0].headers["authorization"] == "token ghp_personnel"


async def test_private_email_is_read_from_the_account_emails() -> None:
    emails = [
        {"email": "vieux@acme.test", "primary": False, "verified": True},
        {"email": "gael@acme.test", "primary": True, "verified": True},
    ]
    http, _ = _http(
        {
            "/user": httpx.Response(200, json={"login": "gael", "id": 7, "email": None}),
            "/user/emails": httpx.Response(200, json=emails),
        }
    )

    account = await fetch_account(http, ROOT, TOKEN)

    assert (account.email, account.email_origin) == ("gael@acme.test", EmailOrigin.EMAILS)
    # Sans nom affiché, le login en tient lieu.
    assert account.name == "gael"


async def test_without_any_readable_email_the_noreply_address_is_used_visibly() -> None:
    http, _ = _http(
        {
            "/user": httpx.Response(200, json={"login": "gael", "id": 7, "email": ""}),
            "/user/emails": httpx.Response(403),
        }
    )

    account = await fetch_account(http, ROOT, TOKEN)

    assert account.email == "7+gael@users.noreply.github.com"
    assert account.email_origin is EmailOrigin.NOREPLY


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(401), ForgeRefusal.REFUSED),
        (httpx.Response(403), ForgeRefusal.REFUSED),
        (httpx.Response(500), ForgeRefusal.UNEXPECTED),
        (httpx.Response(200, json={"id": 7}), ForgeRefusal.UNEXPECTED),
    ],
    ids=["401", "403", "500", "sans-login"],
)
async def test_a_token_the_forge_does_not_accept_says_why(
    response: httpx.Response, reason: ForgeRefusal
) -> None:
    http, _ = _http({"/user": response})

    with pytest.raises(ForgeCheckError) as caught:
        await fetch_account(http, ROOT, TOKEN)

    assert caught.value.reason is reason


async def test_unreachable_forge_is_named() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))

    with pytest.raises(ForgeCheckError) as caught:
        await fetch_account(http, ROOT, TOKEN)

    assert caught.value.reason is ForgeRefusal.UNREACHABLE


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda: httpx.Response(200, json={"permissions": {"push": True}}), True),
        (lambda: httpx.Response(200, json={"permissions": {"pull": True, "push": False}}), False),
        (lambda: httpx.Response(404), False),
        (lambda: httpx.Response(502), None),
    ],
    ids=["ecriture", "lecture-seule", "invisible", "forge-muette"],
)
async def test_write_right_on_a_repository(
    make: Callable[[], httpx.Response], expected: bool | None
) -> None:
    http, seen = _http({"/repos/acme/retrait": make()})

    assert await can_write(http, ROOT, TOKEN, "acme", "retrait") is expected
    assert seen[0].url.path == "/repos/acme/retrait"
