from __future__ import annotations

import json

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from miles.apikeys.model import KeyPrincipal
from miles.apikeys.service import ApiKeysService

log = structlog.get_logger(__name__)

PRINCIPAL_STATE = "miles_principal"
# Les services de Miles : dans l'app MCP montée, `request.app` est l'app du SDK, pas Miles.
SERVICES_STATE = "miles_services"


def presented_key(headers: dict[bytes, bytes]) -> str | None:
    """La clé présentée : `Authorization: Bearer` ou `X-API-Key`, jamais l'URL (critère 6).

    Les deux en-têtes portant deux valeurs différentes : aucune n'est retenue. Choisir
    l'une reviendrait à laisser l'appelant décider laquelle on vérifie.
    """
    found: set[str] = set()
    authorization = headers.get(b"authorization", b"").decode("latin-1").strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            return None
        found.add(value.strip())
    api_key = headers.get(b"x-api-key", b"").decode("latin-1").strip()
    if api_key:
        found.add(api_key)
    return found.pop() if len(found) == 1 else None


class ApiKeyAuth:
    """Garde de la surface MCP : sans clé active, rien ne passe (fail closed).

    Hors de la passerelle des sessions, qui ne garde que /api : la surface MCP n'accepte
    aucune session, et l'IHM n'accepte aucune clé (critère 9). Un seul refus, 401, quelle
    que soit la raison, pour ne pas dire de l'extérieur si une clé existe (critère 5).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        service: ApiKeysService = scope["app"].state.api_keys
        raw = presented_key(dict(scope["headers"]))
        principal: KeyPrincipal | None = None
        if raw is not None:
            principal = await service.resolve_authenticate(raw)
        if principal is None:
            # Ni la clé ni son préfixe au journal : une clé mal saisie reste un secret.
            log.info("mcp_acces_refuse", presented=raw is not None)
            await _unauthorized(send)
            return
        state = scope.setdefault("state", {})
        state[PRINCIPAL_STATE] = principal
        state[SERVICES_STATE] = scope["app"].state
        await self.app(scope, receive, send)


async def _unauthorized(send: Send) -> None:
    body = json.dumps({"detail": "cle_requise"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="miles-mcp"'),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
