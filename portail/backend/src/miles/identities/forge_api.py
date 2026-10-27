from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote, urlsplit

import httpx
import structlog

from miles.secrets.model import Secret

log = structlog.get_logger(__name__)

GITHUB_HOST = "github.com"
GITHUB_API = "https://api.github.com"


class ForgeRefusal(StrEnum):
    """Pourquoi un jeton n'a pas pu être vérifié : jamais un simple échec."""

    REFUSED = "jeton_refuse"
    UNREACHABLE = "forge_injoignable"
    UNEXPECTED = "reponse_inattendue"


class ForgeCheckError(Exception):
    def __init__(self, reason: ForgeRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


class UnsupportedForgeError(Exception):
    """Connexion vers une forge que Miles ne sait pas interroger (GitHub seul en service)."""


class EmailOrigin(StrEnum):
    # D'où vient l'e-mail des commits, montré dans le profil : un repli doit se voir.
    PUBLIC = "public"
    EMAILS = "emails"
    NOREPLY = "noreply"


@dataclass(frozen=True)
class ForgeAccount:
    login: str
    name: str
    email: str
    email_origin: EmailOrigin


def api_root(base_url: str, extra_hosts: Iterable[str]) -> str:
    """API de la forge d'une connexion git, déduite de son adresse déjà validée.

    GitHub seul en service ; les hôtes de test (`extra_hosts`) sont les forges Gitea
    jetables des tests d'intégration, dont l'API vit sous /api/v1.
    """
    parts = urlsplit(base_url)
    host = parts.netloc.lower()
    if host == GITHUB_HOST:
        return GITHUB_API
    if host in {h.lower() for h in extra_hosts}:
        return f"{parts.scheme}://{host}/api/v1"
    raise UnsupportedForgeError(host)


def _headers(token: Secret) -> dict[str, str]:
    # Point d'injection du jeton personnel : déballé ici seulement, jamais journalisé.
    return {"Authorization": f"token {token.reveal()}", "Accept": "application/json"}


async def _get(http: httpx.AsyncClient, url: str, token: Secret) -> httpx.Response:
    try:
        return await http.get(url, headers=_headers(token))
    except httpx.HTTPError as exc:
        log.warning("forge_injoignable", url=url, reason=type(exc).__name__)
        raise ForgeCheckError(ForgeRefusal.UNREACHABLE) from None


async def fetch_account(http: httpx.AsyncClient, root: str, token: Secret) -> ForgeAccount:
    """Compte du jeton, et le nom et l'e-mail que porteront ses commits."""
    user = await _get(http, f"{root}/user", token)
    if user.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise ForgeCheckError(ForgeRefusal.REFUSED)
    if user.status_code != httpx.codes.OK:
        raise ForgeCheckError(ForgeRefusal.UNEXPECTED)
    data = user.json()
    login = data.get("login")
    if not isinstance(login, str) or not login:
        raise ForgeCheckError(ForgeRefusal.UNEXPECTED)
    # Nom affiché absent : le login en tient lieu, il identifie le compte sans ambiguïté.
    name = data.get("name") or data.get("full_name") or login
    email, origin = await _email(http, root, token, data, login)
    return ForgeAccount(login, str(name), email, origin)


async def _email(
    http: httpx.AsyncClient, root: str, token: Secret, user: dict[str, object], login: str
) -> tuple[str, EmailOrigin]:
    public = user.get("email")
    if isinstance(public, str) and public:
        return public, EmailOrigin.PUBLIC
    listed = await _get(http, f"{root}/user/emails", token)
    if listed.status_code == httpx.codes.OK:
        for entry in listed.json():
            if entry.get("primary") and entry.get("verified") and entry.get("email"):
                return str(entry["email"]), EmailOrigin.EMAILS
    # Repli visible (critère du ticket) : l'adresse « noreply » que GitHub rattache au
    # compte. Les commits restent attribués à la bonne personne, sans exposer d'adresse.
    return f"{user.get('id')}+{login}@users.noreply.github.com", EmailOrigin.NOREPLY


async def can_write(
    http: httpx.AsyncClient, root: str, token: Secret, owner: str, name: str
) -> bool | None:
    """Le compte du jeton peut-il pousser sur ce dépôt ? None : la forge ne l'a pas dit."""
    url = f"{root}/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    try:
        response = await _get(http, url, token)
    except ForgeCheckError:
        return None
    if response.status_code == httpx.codes.NOT_FOUND:
        # Un dépôt privé invisible pour ce compte : il ne peut donc pas y écrire.
        return False
    if response.status_code != httpx.codes.OK:
        return None
    permissions = response.json().get("permissions") or {}
    return bool(permissions.get("push"))
