from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from miles.mcp_api.server import MCP_PATH
from miles.oauth.flow import OAuthFlow
from miles.oauth.model import OAuthError

# Hors de /api, donc hors de la passerelle des sessions : ces adresses sont appelées par
# le client OAuth (claude.ai) sans session, et ne servent rien d'autre que ce protocole.
router = APIRouter()

# Ce que le client lit pour savoir comment obtenir un jeton : jamais en cache, puisqu'un
# changement d'adresse publique doit se voir à la connexion suivante.
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _public_url(request: Request) -> str | None:
    public_url: str | None = getattr(request.app.state, "public_url", None)
    return public_url


def _unconfigured() -> JSONResponse:
    # Sans MILES_PUBLIC_URL, Miles ne sait pas sous quelle adresse il est joint : il
    # n'annonce rien plutôt qu'une adresse devinée qu'un client suivrait.
    return JSONResponse(status_code=404, content={"detail": "oauth_non_configure"})


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/.well-known/oauth-protected-resource/mcp/")
async def protected_resource(request: Request) -> JSONResponse:
    """Métadonnées de la ressource MCP (RFC 9728) : où obtenir un jeton pour elle."""
    public_url = _public_url(request)
    if public_url is None:
        return _unconfigured()
    return JSONResponse(
        {
            "resource": public_url + MCP_PATH,
            "authorization_servers": [public_url],
            "bearer_methods_supported": ["header"],
            "resource_name": "Miles",
        },
        headers=_NO_STORE,
    )


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server(request: Request) -> JSONResponse:
    """Métadonnées du serveur d'autorisation (RFC 8414) : code + PKCE S256, clients publics."""
    public_url = _public_url(request)
    if public_url is None:
        return _unconfigured()
    return JSONResponse(
        {
            "issuer": public_url,
            "authorization_endpoint": f"{public_url}/oauth/authorize",
            "token_endpoint": f"{public_url}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            # Clients publics seulement : pas de secret à garder chez claude.ai, PKCE suffit.
            "token_endpoint_auth_methods_supported": ["none"],
        },
        headers=_NO_STORE,
    )


@router.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    """Échange d'un code ou d'un jeton de rafraîchissement (RFC 6749 §4.1.3 et §6)."""
    flow: OAuthFlow = request.app.state.oauth_flow
    form = await request.form()
    fields = {k: v for k, v in form.items() if isinstance(v, str)}
    try:
        issued = await flow.resolve_token(fields)
    except OAuthError as exc:
        # Ni le code ni le jeton présentés au journal : ce sont des secrets.
        content = {"error": exc.error, "error_description": exc.description}
        return JSONResponse(status_code=exc.status, content=content, headers=_NO_STORE)
    return JSONResponse(issued, headers=_NO_STORE)
