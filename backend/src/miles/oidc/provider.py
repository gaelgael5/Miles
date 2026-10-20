from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from miles.oidc.model import OidcError
from miles.secrets.model import Secret

# Algorithmes asymétriques seulement. Ni « none », ni HS* : un HS256 se vérifierait
# avec le secret client, que tout porteur de ce secret pourrait alors imiter.
ALLOWED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
# Tolérance d'horloge entre Miles et le fournisseur, en secondes.
CLOCK_LEEWAY_S = 30
_MAX_SUBJECT_LENGTH = 255


class _NoAuth(httpx.Auth):
    """Secret posté dans le formulaire (client_secret_post) : pas d'en-tête en plus."""


_NO_AUTH = _NoAuth()


class ProviderUnreachableError(OidcError):
    """Le fournisseur ne répond pas, ou pas comme un fournisseur OIDC."""


class ProviderRefusedError(OidcError):
    """Le fournisseur a refusé l'échange (code, PKCE, identifiants client)."""


class InvalidTokenError(OidcError):
    """Jeton refusé : signature, émetteur, audience, expiration ou nonce."""


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    token_auth_methods: frozenset[str]
    signing_algorithms: frozenset[str]


@dataclass(frozen=True)
class Identity:
    subject: str
    display_name: str | None
    email: str | None


@dataclass(frozen=True)
class LoginAttempt:
    state: str
    nonce: str
    code_verifier: str

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_login_attempt() -> LoginAttempt:
    # state : lie le retour à ce navigateur ; nonce : lie le jeton à cette tentative ;
    # PKCE : un code intercepté ne s'échange pas sans le vérificateur.
    return LoginAttempt(
        secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    )


def state_digest(state: str) -> bytes:
    return hashlib.sha256(state.encode("utf-8")).digest()


def _endpoint(document: Mapping[str, Any], key: str, allow_http: bool) -> str:
    value = document.get(key)
    schemes = {"https", "http"} if allow_http else {"https"}
    if not isinstance(value, str) or urlsplit(value).scheme not in schemes:
        raise ProviderUnreachableError(f"métadonnées OIDC sans {key} valide")
    return value


async def fetch_metadata(
    http: httpx.AsyncClient, issuer: str, allow_http: bool
) -> ProviderMetadata:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = await http.get(url)
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderUnreachableError(
            f"découverte OIDC impossible : {type(exc).__name__}"
        ) from None
    if not isinstance(document, dict):
        raise ProviderUnreachableError("métadonnées OIDC illisibles")
    # L'émetteur annoncé doit être exactement celui déclaré (OpenID Discovery §4.3) :
    # sinon un document servi ailleurs ferait accepter les jetons d'un autre émetteur.
    if document.get("issuer") != issuer:
        raise ProviderUnreachableError("l'émetteur annoncé diffère de l'émetteur déclaré")
    methods = document.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
    algorithms = document.get("id_token_signing_alg_values_supported", ["RS256"])
    return ProviderMetadata(
        issuer=issuer,
        authorization_endpoint=_endpoint(document, "authorization_endpoint", allow_http),
        token_endpoint=_endpoint(document, "token_endpoint", allow_http),
        jwks_uri=_endpoint(document, "jwks_uri", allow_http),
        token_auth_methods=frozenset(m for m in methods if isinstance(m, str)),
        signing_algorithms=frozenset(a for a in algorithms if isinstance(a, str)),
    )


def authorization_url(
    metadata: ProviderMetadata,
    client_id: str,
    scopes: str,
    redirect_uri: str,
    attempt: LoginAttempt,
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": attempt.state,
            "nonce": attempt.nonce,
            "code_challenge": attempt.code_challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in metadata.authorization_endpoint else "?"
    return f"{metadata.authorization_endpoint}{separator}{query}"


async def exchange_code(
    http: httpx.AsyncClient,
    metadata: ProviderMetadata,
    client_id: str,
    client_secret: Secret,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> str:
    """Échange le code contre l'ID token. Le secret client n'est déballé qu'ici."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    auth: httpx.Auth
    if "client_secret_basic" in metadata.token_auth_methods:
        auth = httpx.BasicAuth(client_id, client_secret.reveal())
    elif "client_secret_post" in metadata.token_auth_methods:
        form |= {"client_id": client_id, "client_secret": client_secret.reveal()}
        auth = _NO_AUTH
    else:
        raise ProviderRefusedError("aucune méthode d'authentification client commune")
    try:
        response = await http.post(metadata.token_endpoint, data=form, auth=auth)
    except httpx.HTTPError as exc:
        raise ProviderUnreachableError(
            f"point de jeton injoignable : {type(exc).__name__}"
        ) from None
    if response.status_code != httpx.codes.OK:
        raise ProviderRefusedError(f"échange de code refusé (HTTP {response.status_code})")
    try:
        token = response.json().get("id_token")
    except ValueError:
        token = None
    if not isinstance(token, str):
        raise ProviderRefusedError("réponse de jeton sans id_token")
    return token


async def fetch_jwks(http: httpx.AsyncClient, metadata: ProviderMetadata) -> jwt.PyJWKSet:
    try:
        response = await http.get(metadata.jwks_uri)
        response.raise_for_status()
        return jwt.PyJWKSet.from_dict(response.json())
    except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as exc:
        raise ProviderUnreachableError(
            f"clés du fournisseur illisibles : {type(exc).__name__}"
        ) from None


def verify_id_token(
    token: str,
    jwks: jwt.PyJWKSet,
    metadata: ProviderMetadata,
    client_id: str,
    nonce: str,
) -> Identity:
    """Vérifie signature, émetteur, audience, expiration et nonce — tous, toujours.

    Aucune option de contournement, même en test : un jeton non vérifié qui passe une
    seule fois ouvre une session à qui l'a forgé.
    """
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        allowed = ALLOWED_ALGORITHMS & metadata.signing_algorithms
        if algorithm not in allowed:
            raise InvalidTokenError(f"algorithme refusé : {algorithm!r}")
        key = _signing_key(jwks, header.get("kid"))
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=[algorithm],
            audience=client_id,
            issuer=metadata.issuer,
            leeway=CLOCK_LEEWAY_S,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"jeton refusé : {type(exc).__name__}") from None
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise InvalidTokenError("nonce absent ou différent de celui émis")
    audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    # Plusieurs audiences : le jeton doit nous désigner comme partie autorisée (OIDC §3.1.3.7).
    if len(audiences) > 1 and claims.get("azp") != client_id:
        raise InvalidTokenError("jeton à audiences multiples sans azp pour ce client")
    subject = claims["sub"]
    if not isinstance(subject, str) or not 0 < len(subject) <= _MAX_SUBJECT_LENGTH:
        raise InvalidTokenError("sub absent ou invalide")
    return Identity(
        subject, _text_claim(claims, "name", "preferred_username"), _text_claim(claims, "email")
    )


def _signing_key(jwks: jwt.PyJWKSet, kid: object) -> jwt.PyJWK:
    if isinstance(kid, str):
        for key in jwks.keys:
            if key.key_id == kid:
                return key
        raise InvalidTokenError("clé de signature inconnue du fournisseur")
    if len(jwks.keys) == 1:
        return jwks.keys[0]
    raise InvalidTokenError("jeton sans kid et plusieurs clés publiées")


def _text_claim(claims: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None
