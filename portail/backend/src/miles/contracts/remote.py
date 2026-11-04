from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
import structlog

from miles.contracts.openapi import MAX_CONTRACT_BYTES

log = structlog.get_logger(__name__)

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolve = Callable[[str, int], Awaitable[list[IpAddress]]]
SCHEMES = {"http": 80, "https": 443}
MAX_REDIRECTS = 3
FETCH_TIMEOUT = httpx.Timeout(10.0)


class RemoteContractError(Exception):
    """Lecture refusée ou échouée, avec une raison que l'écran sait dire."""

    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason, self.status = reason, status


def reachable_by_miles(address: IpAddress) -> bool:
    """Adresses que le back-office accepte d'interroger pour le compte de l'administrateur.

    Le contenu lu revient à l'écran : sans cette garde, la saisie d'une adresse ferait
    lire au serveur ce que lui seul voit — métadonnées du cloud (lien local), ses propres
    services (boucle locale). Les réseaux privés restent permis : un tiers de la maison
    publie souvent son contrat sur le réseau interne.
    """
    return not (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    )


async def resolve_host(host: str, port: int) -> list[IpAddress]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [ipaddress.ip_address(info[4][0]) for info in infos]


@dataclass(frozen=True)
class _Target:
    url: str
    host: str
    port: int
    scheme: str


def _target(raw: str) -> _Target:
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError as exc:
        raise RemoteContractError("adresse_invalide") from exc
    # Identifiants dans l'adresse refusés : ils finiraient dans les journaux d'accès du tiers
    # et dans l'historique du navigateur, pas dans le gestionnaire de secrets.
    if parts.scheme not in SCHEMES or not parts.hostname or parts.username or parts.password:
        raise RemoteContractError("adresse_invalide")
    return _Target(parts.geturl(), parts.hostname, port or SCHEMES[parts.scheme], parts.scheme)


@dataclass(frozen=True)
class RemoteContracts:
    """Lit un contrat publié à une adresse http(s), sans rien écrire (502b24c2, 22/10/2026)."""

    http: httpx.AsyncClient
    resolve: Resolve = resolve_host
    allowed: Callable[[IpAddress], bool] = reachable_by_miles
    max_bytes: int = MAX_CONTRACT_BYTES

    async def resolve_fetch(self, raw_url: str) -> str:
        target = _target(raw_url)
        # Redirections suivies à la main : chaque saut repasse par la garde d'adresse,
        # sinon un tiers complaisant renverrait vers la boucle locale.
        for _ in range(MAX_REDIRECTS + 1):
            response, body = await self._get(target)
            if not response.is_redirect:
                return _text(response, body)
            location = response.headers.get("location", "")
            target = _target(urljoin(target.url, location))
        raise RemoteContractError("trop_de_redirections")

    async def _pinned_address(self, target: _Target) -> IpAddress:
        try:
            addresses = await self.resolve(target.host, target.port)
        except OSError as exc:
            raise RemoteContractError("injoignable") from exc
        # Toutes les adresses passent la garde, pas seulement la première : le système
        # choisirait sinon celle qu'un DNS hostile met en tête au moment de la connexion.
        if not addresses or not all(self.allowed(a) for a in addresses):
            log.warning("contrat_distant_refuse", host=target.host, reason="adresse_interdite")
            raise RemoteContractError("adresse_interdite")
        return addresses[0]

    async def _get(self, target: _Target) -> tuple[httpx.Response, bytes]:
        address = await self._pinned_address(target)
        # Connexion à l'adresse vérifiée, pas au nom : une seconde résolution DNS pourrait
        # rendre une autre adresse (rebinding). Le nom reste dans Host et dans le SNI, pour
        # que l'hôte virtuel et le certificat soient ceux du tiers.
        pinned = httpx.URL(target.url).copy_with(host=str(address), port=target.port)
        request = self.http.build_request(
            "GET",
            pinned,
            headers={"Host": urlsplit(target.url).netloc},
            extensions={"sni_hostname": target.host},
            timeout=FETCH_TIMEOUT,
        )
        try:
            response = await self.http.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            log.warning("contrat_distant_injoignable", host=target.host, reason=type(exc).__name__)
            raise RemoteContractError("injoignable") from exc
        try:
            return response, await self._bounded_body(response)
        finally:
            await response.aclose()

    async def _bounded_body(self, response: httpx.Response) -> bytes:
        # Lu par morceaux et coupé à la borne : un en-tête Content-Length peut mentir ou
        # manquer, et le contrat entier ne doit jamais tenir en mémoire au-delà.
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self.max_bytes:
                raise RemoteContractError("trop_volumineux")
            chunks.append(chunk)
        return b"".join(chunks)


def _text(response: httpx.Response, body: bytes) -> str:
    if response.status_code != httpx.codes.OK:
        raise RemoteContractError("statut", response.status_code)
    try:
        return body.decode(response.charset_encoding or "utf-8")
    except (UnicodeDecodeError, LookupError) as exc:
        raise RemoteContractError("encodage") from exc
