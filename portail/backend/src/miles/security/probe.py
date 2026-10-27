from __future__ import annotations

from enum import StrEnum
from urllib.parse import quote, urlsplit

import httpx
import structlog
from miles_socle.secrets.model import Secret

log = structlog.get_logger(__name__)


class Outcome(StrEnum):
    """Les quatre diagnostics du ticket 5a56c6a9 : jamais un simple succès/échec."""

    OK = "ok"
    REALM_UNKNOWN = "realm_inconnu"
    UNREACHABLE = "injoignable"
    REFUSED = "refuse"


def realm_issuer(base_url: str, realm: str) -> str:
    return f"{base_url.rstrip('/')}/realms/{quote(realm, safe='')}"


async def probe_keycloak(
    http: httpx.AsyncClient,
    base_url: str,
    realm: str,
    client_id: str,
    client_secret: Secret,
    allow_http: bool,
) -> Outcome:
    """Interroge vraiment le service : découverte du realm, puis jeton de compte de service.

    Le jeton prouve ce que la découverte ne dit pas : que Miles a les droits de
    s'adresser au service avec ce client et ce secret.
    """
    issuer = realm_issuer(base_url, realm)
    try:
        discovery = await http.get(f"{issuer}/.well-known/openid-configuration")
    except httpx.HTTPError as exc:
        log.warning("securite_injoignable", base_url=base_url, reason=type(exc).__name__)
        return Outcome.UNREACHABLE
    if discovery.status_code == httpx.codes.NOT_FOUND:
        return Outcome.REALM_UNKNOWN
    token_endpoint = _token_endpoint(discovery, allow_http)
    if token_endpoint is None:
        return Outcome.UNREACHABLE
    try:
        token = await http.post(
            token_endpoint,
            data={"grant_type": "client_credentials"},
            # Point d'injection du secret : déballé ici seulement.
            auth=httpx.BasicAuth(client_id, client_secret.reveal()),
        )
    except httpx.HTTPError as exc:
        log.warning("securite_injoignable", base_url=base_url, reason=type(exc).__name__)
        return Outcome.UNREACHABLE
    if token.status_code == httpx.codes.OK:
        return Outcome.OK
    if token.status_code in (httpx.codes.BAD_REQUEST, httpx.codes.UNAUTHORIZED):
        return Outcome.REFUSED
    return Outcome.UNREACHABLE


def _token_endpoint(response: httpx.Response, allow_http: bool) -> str | None:
    if response.status_code != httpx.codes.OK:
        return None
    try:
        endpoint = response.json().get("token_endpoint")
    except ValueError:
        return None
    schemes = {"https", "http"} if allow_http else {"https"}
    if not isinstance(endpoint, str) or urlsplit(endpoint).scheme not in schemes:
        return None
    return endpoint
