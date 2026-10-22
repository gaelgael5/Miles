from __future__ import annotations

import os
import secrets as random
import tempfile
from pathlib import Path

import httpx
import pytest

from miles.chains.service import EVENT_TYPES as CHAIN_EVENTS
from miles.chains.service import ChainsService
from miles.contracts.remote import RemoteContracts
from miles.contracts.service import EVENT_TYPES as CONTRACT_EVENTS
from miles.contracts.service import ContractsService
from miles.datamodels.service import EVENT_TYPES as DATA_MODEL_EVENTS
from miles.datamodels.service import DataModelsService
from miles.events.model import EventTypeCatalog
from miles.git.workdirs import WorkDirs
from miles.gitaccess.connections import ConnectionsService
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.model import EVENT_TYPES as GITACCESS_EVENTS
from miles.gitaccess.resolver import AccessResolver
from miles.identities.service import EVENT_TYPES as IDENTITY_EVENTS
from miles.identities.service import GitIdentitiesService
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from miles.sources.service import EVENT_TYPES as SOURCE_EVENTS
from miles.sources.service import SourcesService
from miles.transform.api_catalog import CatalogService
from miles.workshop.branches import EVENT_TYPES as BRANCH_EVENTS
from miles.workshop.branches import BranchesService
from miles.workshop.service import EVENT_TYPES as WORKSHOP_EVENTS
from miles.workshop.service import WorkshopService
from miles.workshop.target import WorkBranches
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
    """Branche secrets, connexions, workspaces et modèles comme le fait app.py."""
    catalog = EventTypeCatalog(
        SECRET_EVENTS
        | WORKSPACE_EVENTS
        | GITACCESS_EVENTS
        | DATA_MODEL_EVENTS
        | WORKSHOP_EVENTS
        | CONTRACT_EVENTS
        | BRANCH_EVENTS
        | IDENTITY_EVENTS
        | CHAIN_EVENTS
        | SOURCE_EVENTS
    )
    cipher = SecretCipher(os.urandom(32))
    secrets = SecretsService(portal.pool, cipher, catalog, utc_now)
    resolver = AccessResolver(secrets)
    verifier = DependentsVerifier(portal.pool, catalog, utc_now, hosts)
    state = portal.app.state
    state.secrets = secrets
    state.git_connections = ConnectionsService(
        portal.pool, resolver, verifier, catalog, utc_now, hosts
    )
    state.workspaces = WorkspacesService(portal.pool, resolver, catalog, utc_now, hosts)
    # Copies de travail dans un dossier jetable propre à l'exécution, comme le volume en service.
    workdirs = WorkDirs(Path(tempfile.mkdtemp(prefix="miles-it-workdirs-")))
    branches = WorkBranches(portal.pool, state.workspaces, resolver, workdirs, hosts)
    state.data_models = DataModelsService(portal.pool, branches, catalog, utc_now)
    state.workshop = WorkshopService(portal.pool, branches, catalog, utc_now)
    state.contracts = ContractsService(portal.pool, branches, catalog, utc_now)
    # Sans connexion ouverte tant que rien n'est lu : les tests n'y font passer que des
    # adresses refusées avant toute requête.
    state.remote_contracts = RemoteContracts(httpx.AsyncClient())
    state.branches = BranchesService(portal.pool, branches, catalog, utc_now)
    state.template_catalog = CatalogService(branches)
    state.chains = ChainsService(portal.pool, branches, catalog, utc_now)
    state.sources = SourcesService(portal.pool, branches, catalog, utc_now)
    state.git_identities = GitIdentitiesService(
        portal.pool, cipher, httpx.AsyncClient(), catalog, utc_now, hosts
    )


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
