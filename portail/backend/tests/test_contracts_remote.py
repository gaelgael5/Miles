from __future__ import annotations

import ipaddress
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from miles.contracts.remote import (
    IpAddress,
    RemoteContractError,
    RemoteContracts,
    Resolve,
    reachable_by_miles,
)

CONTRACT = "openapi: 3.1.0\ninfo: {title: Évènements, version: '1'}\npaths: {}\n"
PUBLIC = ipaddress.ip_address("93.184.215.14")


def _resolver(table: dict[str, list[str]]) -> Resolve:
    async def resolve(host: str, port: int) -> list[IpAddress]:
        if host not in table:
            raise OSError("nom inconnu")
        return [ipaddress.ip_address(a) for a in table[host]]

    return resolve


def _remote(
    handler: Callable[[httpx.Request], httpx.Response],
    table: dict[str, list[str]] | None = None,
    max_bytes: int = 1024,
) -> tuple[RemoteContracts, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    resolve = _resolver(table or {"tiers.example": [str(PUBLIC)]})
    return RemoteContracts(http, resolve=resolve, max_bytes=max_bytes), seen


async def test_contract_is_read_from_the_checked_address_under_the_third_party_name() -> None:
    remote, seen = _remote(lambda _: httpx.Response(200, content=CONTRACT.encode()))

    text = await remote.resolve_fetch("https://tiers.example:8443/api/openapi.yaml?v=2")

    assert text == CONTRACT
    [request] = seen
    assert str(request.url) == f"https://{PUBLIC}:8443/api/openapi.yaml?v=2"
    assert request.headers["host"] == "tiers.example:8443"
    assert request.extensions["sni_hostname"] == "tiers.example"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://tiers.example/c.yaml",
        "file:///etc/passwd",
        "https:///sans-hote",
        "https://moi:secret@tiers.example/c.yaml",
        "https://tiers.example:99999/c.yaml",
        "pas une adresse",
    ],
)
async def test_malformed_address_is_refused_before_any_request(url: str) -> None:
    remote, seen = _remote(lambda _: httpx.Response(200))

    with pytest.raises(RemoteContractError) as caught:
        await remote.resolve_fetch(url)

    assert (caught.value.reason, seen) == ("adresse_invalide", [])


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["169.254.169.254"], ["::1"], ["::"], [str(PUBLIC), "127.0.0.1"]],
    ids=["boucle", "metadonnees", "boucle-v6", "non-specifiee", "une-sur-deux"],
)
async def test_address_resolving_to_the_server_itself_is_refused(addresses: list[str]) -> None:
    remote, seen = _remote(lambda _: httpx.Response(200), {"piege.example": addresses})

    with pytest.raises(RemoteContractError) as caught:
        await remote.resolve_fetch("http://piege.example/c.yaml")

    assert (caught.value.reason, seen) == ("adresse_interdite", [])


def test_private_network_stays_reachable() -> None:
    assert reachable_by_miles(ipaddress.ip_address("10.20.0.5"))
    assert reachable_by_miles(ipaddress.ip_address("192.168.1.10"))


async def test_redirect_is_followed_only_through_the_guard() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "tiers.example":
            return httpx.Response(302, headers={"location": "http://piege.example/x"})
        return httpx.Response(200, content=b"secret")

    remote, seen = _remote(
        handler, {"tiers.example": [str(PUBLIC)], "piege.example": ["127.0.0.1"]}
    )

    with pytest.raises(RemoteContractError) as caught:
        await remote.resolve_fetch("https://tiers.example/c.yaml")

    assert caught.value.reason == "adresse_interdite"
    assert len(seen) == 1


async def test_relative_redirect_is_followed_then_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ancien":
            return httpx.Response(301, headers={"location": "/nouveau"})
        if request.url.path == "/nouveau":
            return httpx.Response(200, content=CONTRACT.encode())
        return httpx.Response(302, headers={"location": "/boucle"})

    remote, seen = _remote(handler)

    assert await remote.resolve_fetch("https://tiers.example/ancien") == CONTRACT
    with pytest.raises(RemoteContractError) as caught:
        await remote.resolve_fetch("https://tiers.example/boucle")
    assert caught.value.reason == "trop_de_redirections"
    assert len(seen) == 2 + 4


@pytest.mark.parametrize(
    ("response", "reason", "status"),
    [
        (httpx.Response(404), "statut", 404),
        (httpx.Response(200, content=b"x" * 1025), "trop_volumineux", None),
        (httpx.Response(200, content=b"\xff\xfe\xfa"), "encodage", None),
    ],
    ids=["absent", "trop-gros", "pas-du-texte"],
)
async def test_unusable_answer_says_why(
    response: httpx.Response, reason: str, status: int | None
) -> None:
    remote, _ = _remote(lambda _: response)

    with pytest.raises(RemoteContractError) as caught:
        await remote.resolve_fetch("https://tiers.example/c.yaml")

    assert (caught.value.reason, caught.value.status) == (reason, status)


async def test_unknown_or_silent_host_is_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    remote, _ = _remote(refuse)

    for url in ("https://inconnu.example/c.yaml", "https://tiers.example/c.yaml"):
        with pytest.raises(RemoteContractError) as caught:
            await remote.resolve_fetch(url)
        assert caught.value.reason == "injoignable"


@pytest.fixture
def local_server() -> Iterator[tuple[int, list[str]]]:
    hosts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hosts.append(self.headers["Host"])
            body = CONTRACT.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], hosts
    server.shutdown()


async def test_real_connection_goes_to_the_pinned_address_with_the_named_host(
    local_server: tuple[int, list[str]],
) -> None:
    port, hosts = local_server
    async with httpx.AsyncClient() as http:
        # Garde levée pour ce test seul : la boucle locale est la seule adresse sûre ici.
        remote = RemoteContracts(
            http,
            resolve=_resolver({"tiers.example": ["127.0.0.1"]}),
            allowed=lambda _: True,
        )

        text = await remote.resolve_fetch(f"http://tiers.example:{port}/c.yaml")

    assert (text, hosts) == (CONTRACT, [f"tiers.example:{port}"])
