from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

# Durées retenues à la reprise de la story 9f09cd8b (valeurs conventionnelles).
CODE_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)

# Préfixes lisibles : un jeton qui fuit se reconnaît, et la garde MCP sait sans lecture en
# base s'il s'agit d'une clé de service (mlk_) ou d'un jeton OAuth (mla_).
CODE_PREFIX = "mlc_"
ACCESS_PREFIX = "mla_"
REFRESH_PREFIX = "mlr_"
CLIENT_PREFIX = "mcl_"
TOKEN_RE = re.compile(r"^ml[acr]_[A-Za-z0-9_-]{43}$")
CLIENT_ID_RE = re.compile(r"^mcl_[0-9a-f]{32}$")
GRANT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# RFC 7636 : 43 à 128 caractères non réservés.
VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# Annuaire des auteurs quand le client agit pour une personne : c'est elle qui signe.
LOCAL_KIND, OIDC_KIND = "local", "oidc"


class OAuthError(Exception):
    """Refus au sens de RFC 6749 : un code normalisé, et une explication pour l'humain."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(error)
        self.error, self.description, self.status = error, description, status


@dataclass(frozen=True)
class Person:
    """Qui consent : l'identité (annuaire, sub), et de quoi revérifier ses droits ensuite."""

    directory: str
    subject: str
    kind: str
    email: str | None
    display_name: str


def new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def new_client_id() -> str:
    return CLIENT_PREFIX + secrets.token_hex(16)


def digest(raw: str) -> bytes:
    return hashlib.sha256(raw.encode()).digest()


def pkce_matches(verifier: str, challenge: str) -> bool:
    """S256 seulement : `plain` laisserait passer un défi recopié par qui a vu la requête."""
    if not VERIFIER_RE.match(verifier):
        return False
    computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return hmac.compare_digest(computed.rstrip(b"=").decode(), challenge)


def checked_redirect_uri(uri: str) -> str:
    """Adresse de retour admise à la déclaration d'un client.

    HTTPS, sans fragment ; HTTP seulement vers la boucle locale, pour un client d'essai
    sur poste (RFC 8252). Tout le reste pourrait détourner un code vers un tiers.
    """
    uri = uri.strip()
    parts = urlsplit(uri)
    loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.fragment or not parts.hostname or len(uri) > 300:
        raise ValueError(uri)
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError(uri)
    return uri


def same_resource(asked: str, ours: str) -> bool:
    # Indicateur de ressource (RFC 8707) : la barre finale ne fait pas une autre ressource.
    return asked.rstrip("/") == ours.rstrip("/")
