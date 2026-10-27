from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

# Segments propriétaire / dépôt : ce qu'admet GitHub, rien de plus. L'adresse entre
# ensuite dans une commande git : aucune autre forme ne doit pouvoir y passer.
_SEGMENT = r"[A-Za-z0-9_.-]{1,100}"
_PATH_RE = re.compile(rf"^/({_SEGMENT})/({_SEGMENT}?)(?:\.git)?/?$")
_BASE_PATH_RE = re.compile(rf"^(?:/({_SEGMENT}))?/?$")
GITHUB_HOST = "github.com"
# Avec un jeton (PAT ou jeton fin), GitHub accepte n'importe quel nom ; c'est celui
# qu'emploient ses propres outils, et celui que devflow emploie aussi.
TOKEN_USERNAME = "x-access-token"  # noqa: S105  # nom d'utilisateur conventionnel, pas un secret


class RepositoryUrlError(ValueError):
    """Adresse de dépôt refusée avant toute commande git."""


@dataclass(frozen=True)
class Repository:
    """Dépôt désigné par une adresse normalisée, comparable d'un workspace à l'autre."""

    url: str
    owner: str
    name: str


def parse_repository(raw: str, extra_hosts: Iterable[str] = ()) -> Repository:
    """GitHub seul au premier lot (cadrage) ; `extra_hosts` ne sert qu'aux tests d'intégration.

    Comme devflow : la forge se reconnaît à l'hôte, et chaque forge s'ajoutera ensuite par
    sa propre stratégie. Ici une seule, l'HTTPS par jeton.
    """
    parts = _split(raw, extra_hosts)
    match = _PATH_RE.match(parts.path)
    # « . » et « .. » passent le motif des segments : refusés à part, une adresse ne
    # devant jamais remonter d'un niveau une fois reconstruite.
    if match is None or not match.group(2) or {match.group(1), match.group(2)} & {".", ".."}:
        raise RepositoryUrlError("adresse de la forme https://github.com/<propriétaire>/<dépôt>")
    owner, name = match.group(1), match.group(2)
    # Casse ignorée : GitHub ne distingue pas Owner/Repo de owner/repo, et deux workspaces
    # ne doivent pas pouvoir prendre le même dépôt en jouant sur les majuscules.
    url = f"{parts.scheme}://{parts.netloc.lower()}/{owner.lower()}/{name.lower()}.git"
    return Repository(url, owner, name)


def parse_base_url(raw: str, extra_hosts: Iterable[str] = ()) -> str:
    """Adresse d'une connexion git : la forge, ou une organisation de la forge (21/10/2026).

    Normalisée comme les dépôts (casse ignorée, sans barre finale), pour que « ce dépôt
    est-il sous cette connexion ? » se décide par une simple comparaison de préfixe.
    """
    parts = _split(raw, extra_hosts)
    match = _BASE_PATH_RE.match(parts.path)
    owner = match.group(1) if match else None
    if match is None or owner in {".", ".."}:
        raise RepositoryUrlError("adresse de la forme https://github.com[/<organisation>]")
    base = f"{parts.scheme}://{parts.netloc.lower()}"
    return f"{base}/{owner.lower()}" if owner else base


def repository_under(base_url: str, repo: Repository) -> bool:
    return repo.url.startswith(base_url + "/")


def _split(raw: str, extra_hosts: Iterable[str]) -> SplitResult:
    parts = urlsplit(raw.strip())
    host = parts.netloc.lower()
    allowed_test_host = host in {h.lower() for h in extra_hosts}
    if host != GITHUB_HOST and not allowed_test_host:
        raise RepositoryUrlError("seul GitHub est pris en charge")
    scheme_ok = parts.scheme == "https" or (allowed_test_host and parts.scheme == "http")
    if not scheme_ok or parts.username or parts.password or parts.query or parts.fragment:
        raise RepositoryUrlError("adresse https sans identifiants, requête ni fragment")
    return parts
