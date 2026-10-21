from __future__ import annotations

import os
import secrets as random

import httpx
import pytest

from miles.events.model import EventTypeCatalog
from miles.gitaccess.connections import ConnectionsService
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.model import EVENT_TYPES as GITACCESS_EVENTS
from miles.gitaccess.resolver import AccessResolver
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from miles.workspaces.model import EVENT_TYPES as WORKSPACE_EVENTS
from miles.workspaces.service import WorkspacesService
from tests.integration.portal_stack import PortalStack, utc_now


def env(name: str) -> str:
    # Posés par scripts/run-integration-tests.sh, qui lance une forge Gitea jetable : les
    # droits s'éprouvent par de vrais push, sur de vrais dépôts privés.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} absent : lancer via scripts/run-integration-tests.sh")
    return value


def wire_git(portal: PortalStack, hosts: tuple[str, ...]) -> None:
    """Branche secrets, connexions et workspaces comme le fait app.py."""
    catalog = EventTypeCatalog(SECRET_EVENTS | WORKSPACE_EVENTS | GITACCESS_EVENTS)
    secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
    resolver = AccessResolver(secrets)
    verifier = DependentsVerifier(portal.pool, catalog, utc_now, hosts)
    state = portal.app.state
    state.secrets = secrets
    state.git_connections = ConnectionsService(
        portal.pool, resolver, verifier, catalog, utc_now, hosts
    )
    state.workspaces = WorkspacesService(portal.pool, resolver, catalog, utc_now, hosts)


async def add_secret(client: httpx.AsyncClient, slug: str, kind: str, value: str) -> None:
    body = {"slug": slug, "label": slug, "secret_type": kind, "value": value}
    assert (await client.post("/api/secrets", json=body)).status_code == 201


async def add_connection(client: httpx.AsyncClient, cid: str, base: str, **access: object) -> None:
    body = {"id": cid, "label": cid, "base_url": base} | access
    created = await client.post("/api/git-connections", json=body)
    assert created.status_code == 201, created.text


async def create_workspace(client: httpx.AsyncClient, wid: str = "retrait") -> httpx.Response:
    return await client.post("/api/workspaces", json={"id": wid, "name": f"Nom {wid}"})


async def set_repository(
    client: httpx.AsyncClient, url: str, connection: str, wid: str = "retrait"
) -> httpx.Response:
    body = {
        "git_connection_id": connection,
        "repo_url": url,
        "verification_suffix": random.token_hex(4),
    }
    return await client.put(f"/api/workspaces/{wid}/repository", json=body, timeout=120)


def suffix() -> str:
    return random.token_hex(4)
