from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from miles.oidc.provider import (
    InvalidTokenError,
    LoginAttempt,
    ProviderMetadata,
    ProviderRefusedError,
    ProviderUnreachableError,
    authorization_url,
    exchange_code,
    fetch_jwks,
    fetch_metadata,
    verify_id_token,
)
from miles.secrets.model import Secret

ISSUER = "https://idp.example.org/realms/miles"
CLIENT = "miles-client"
NONCE = "nonce-de-la-tentative"
CLIENT_SECRET = "secret-client-a-ne-pas-voir"


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = _key()
OTHER_KEY = _key()


def _jwks(key: rsa.RSAPrivateKey = KEY, kid: str = "k1") -> jwt.PyJWKSet:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return jwt.PyJWKSet.from_dict({"keys": [public | {"kid": kid, "use": "sig", "alg": "RS256"}]})


METADATA = ProviderMetadata(
    issuer=ISSUER,
    authorization_endpoint=f"{ISSUER}/protocol/openid-connect/auth",
    token_endpoint=f"{ISSUER}/protocol/openid-connect/token",
    jwks_uri=f"{ISSUER}/protocol/openid-connect/certs",
    token_auth_methods=frozenset({"client_secret_basic"}),
    signing_algorithms=frozenset({"RS256", "HS256"}),
)


def _token(
    key: Any = KEY, algorithm: str = "RS256", kid: str | None = "k1", **overrides: Any
) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "alice-sub",
        "aud": CLIENT,
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
        "name": "Alice",
        "email": "alice@example.org",
    } | overrides
    claims = {k: v for k, v in claims.items() if v is not None}
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def test_valid_token_yields_the_identity() -> None:
    identity = verify_id_token(_token(), _jwks(), METADATA, CLIENT, NONCE)

    assert (identity.subject, identity.display_name, identity.email) == (
        "alice-sub",
        "Alice",
        "alice@example.org",
    )


def test_display_name_falls_back_to_preferred_username_then_nothing() -> None:
    token = _token(name=None, preferred_username="alice", email=None)

    identity = verify_id_token(token, _jwks(), METADATA, CLIENT, NONCE)

    assert (identity.display_name, identity.email) == ("alice", None)


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda: _token(key=OTHER_KEY), id="signature-autre-cle"),
        pytest.param(lambda: _token(iss="https://evil.example.org"), id="emetteur"),
        pytest.param(lambda: _token(aud="autre-client"), id="audience"),
        pytest.param(lambda: _token(exp=int(time.time()) - 3600), id="expire"),
        pytest.param(lambda: _token(nonce="autre-nonce"), id="nonce-different"),
        pytest.param(lambda: _token(nonce=None), id="nonce-absent"),
        pytest.param(lambda: _token(sub=None), id="sub-absent"),
        pytest.param(lambda: _token(kid="inconnu"), id="kid-inconnu"),
        pytest.param(lambda: _token(aud=[CLIENT, "autre"]), id="audiences-sans-azp"),
        pytest.param(lambda: _token(key=CLIENT_SECRET.encode() * 2, algorithm="HS256"), id="hs256"),
    ],
)
def test_invalid_tokens_are_refused(make_token: Callable[[], str]) -> None:
    with pytest.raises(InvalidTokenError):
        verify_id_token(make_token(), _jwks(), METADATA, CLIENT, NONCE)


def test_unsigned_token_is_refused() -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    claims = {"iss": ISSUER, "sub": "x", "aud": CLIENT, "nonce": NONCE, "exp": 9999999999}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")

    with pytest.raises(InvalidTokenError, match="algorithme"):
        verify_id_token(f"{header.decode()}.{body.decode()}.", _jwks(), METADATA, CLIENT, NONCE)


def test_multiple_audiences_are_accepted_when_azp_names_us() -> None:
    token = _token(aud=[CLIENT, "autre"], azp=CLIENT)

    assert verify_id_token(token, _jwks(), METADATA, CLIENT, NONCE).subject == "alice-sub"


def test_authorization_url_carries_state_nonce_and_s256_challenge() -> None:
    # Vecteur de la RFC 7636, annexe B.
    attempt = LoginAttempt("S", "N", "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")

    url = authorization_url(METADATA, CLIENT, "openid email", "https://miles/cb", attempt)

    query = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    assert query["code_challenge"] == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert query["code_challenge_method"] == "S256"
    assert (query["state"], query["nonce"], query["response_type"]) == ("S", "N", "code")
    assert "dBjftJeZ4CVP" not in url


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _discovery(**overrides: Any) -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": METADATA.authorization_endpoint,
        "token_endpoint": METADATA.token_endpoint,
        "jwks_uri": METADATA.jwks_uri,
    } | overrides


async def test_fetch_metadata_reads_discovery_with_spec_defaults() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{ISSUER}/.well-known/openid-configuration"
        return httpx.Response(200, json=_discovery())

    async with _client(handler) as http:
        metadata = await fetch_metadata(http, ISSUER, allow_http=False)

    assert metadata.token_auth_methods == {"client_secret_basic"}
    assert metadata.signing_algorithms == {"RS256"}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=_discovery(issuer="https://autre.example.org")),
        httpx.Response(200, json=_discovery(token_endpoint="http://idp.example.org/token")),
        httpx.Response(200, json=_discovery(jwks_uri=None)),
        httpx.Response(200, text="pas du json"),
        httpx.Response(503),
    ],
)
async def test_fetch_metadata_refuses_wrong_or_unreachable_providers(
    response: httpx.Response,
) -> None:
    async with _client(lambda request: response) as http:
        with pytest.raises(ProviderUnreachableError):
            await fetch_metadata(http, ISSUER, allow_http=False)


async def test_fetch_metadata_reports_network_failure_as_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé")

    async with _client(handler) as http:
        with pytest.raises(ProviderUnreachableError):
            await fetch_metadata(http, ISSUER, allow_http=False)


async def test_exchange_uses_basic_auth_and_returns_the_id_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id_token": "jeton", "access_token": "a"})

    async with _client(handler) as http:
        token = await exchange_code(
            http, METADATA, CLIENT, Secret(CLIENT_SECRET), "code", "verif", "https://miles/cb"
        )

    assert token == "jeton"
    expected = base64.b64encode(f"{CLIENT}:{CLIENT_SECRET}".encode()).decode()
    assert seen[0].headers["authorization"] == f"Basic {expected}"
    assert b"code_verifier=verif" in seen[0].content
    assert CLIENT_SECRET.encode() not in seen[0].content


async def test_exchange_posts_the_secret_when_only_client_secret_post_is_supported() -> None:
    seen: list[httpx.Request] = []
    metadata = ProviderMetadata(
        **{**METADATA.__dict__, "token_auth_methods": frozenset({"client_secret_post"})}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id_token": "jeton"})

    async with _client(handler) as http:
        await exchange_code(http, metadata, CLIENT, Secret(CLIENT_SECRET), "c", "v", "https://m/cb")

    assert "authorization" not in seen[0].headers
    assert b"client_secret=" + CLIENT_SECRET.encode() in seen[0].content


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(200, json={"access_token": "sans id_token"}),
    ],
)
async def test_exchange_refusals_are_explicit(response: httpx.Response) -> None:
    async with _client(lambda request: response) as http:
        with pytest.raises(ProviderRefusedError):
            await exchange_code(
                http, METADATA, CLIENT, Secret(CLIENT_SECRET), "c", "v", "https://m/cb"
            )


async def test_fetch_jwks_reads_the_published_keys() -> None:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [public | {"kid": "k1"}]})

    async with _client(handler) as http:
        jwks = await fetch_jwks(http, METADATA)

    assert [k.key_id for k in jwks.keys] == ["k1"]


def test_symmetric_algorithm_is_refused_before_any_key_lookup() -> None:
    # Même annoncé par le fournisseur, HS256 se vérifierait avec le secret client.
    token = _token(key=CLIENT_SECRET.encode() * 2, algorithm="HS256")

    with pytest.raises(InvalidTokenError, match="algorithme refusé"):
        verify_id_token(token, _jwks(), METADATA, CLIENT, NONCE)
