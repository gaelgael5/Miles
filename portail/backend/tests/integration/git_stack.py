from __future__ import annotations

import os
import secrets as random
import tempfile
from pathlib import Path

import httpx
import pytest
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService

from miles.apikeys.service import ApiKeysService
from miles.chains.service import ChainsService
from miles.config import Settings
from miles.contracts.models_service import ContractModelsService
from miles.contracts.remote import RemoteContracts
from miles.contracts.service import ContractsService
from miles.datamodels.service import DataModelsService
from miles.event_types import code_event_types
from miles.git.holdspace import HOLDS_DIR, HoldSpaces
from miles.git.workdirs import WorkDirs
from miles.gitaccess.confide import GitConfidingService
from miles.gitaccess.connections import ConnectionsService
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.resolver import AccessResolver
from miles.identities.service import GitIdentitiesService
from miles.oauth.access import OAuthAccess
from miles.oauth.clients import OAuthClientsService
from miles.oauth.flow import OAuthFlow
from miles.obo.service import ActorIdentitiesService
from miles.pairing.service import PairingService
from miles.sources.service import SourcesService
from miles.storages.service import StoragesService
from miles.transform.api_catalog import CatalogService
from miles.workshop.branches import BranchesService
from miles.workshop.domains_service import DomainsService
from miles.workshop.holds import BranchHoldsService
from miles.workshop.service import WorkshopService
from miles.workshop.shelving import ShelvesService
from miles.workshop.target import WorkBranches
from miles.workshop.targeted import TargetedReads
from miles.workspaces.cultures_service import WorkspaceCulturesService
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
    # LE catalogue du produit, et non une union assemblée ici. Mesuré le 29/10/2026 dans
    # le harnais de l'appariement : assemblé à la main, il contenait des types que
    # `code_event_types()` avait OUBLIÉS — la suite était verte et la stack déployée rendait
    # 500. Un harnais plus généreux que la production est complaisant exactement là où il
    # devait mordre, et c'est la leçon de `LESSONS.md`.
    catalog = EventTypeCatalog(code_event_types())
    cipher = SecretCipher(os.urandom(32))
    secrets = SecretsService(portal.pool, cipher, catalog, utc_now)
    resolver = AccessResolver(secrets)
    verifier = DependentsVerifier(portal.pool, catalog, utc_now, hosts)
    state = portal.app.state
    state.secrets = secrets
    state.git_connections = ConnectionsService(
        portal.pool, resolver, verifier, catalog, utc_now, hosts
    )
    # Le confiage des connexions git. Posé ici comme dans `app.py` : sans module
    # d'enrôlement apparié, chacun de ses déclencheurs ne fait rien — c'est l'état des
    # tests qui n'apparient pas, et c'est ce que `resolve_transmit_after` doit admettre.
    state.identity = PairingService(
        portal.pool, secrets, cipher, catalog, utc_now, httpx.AsyncClient(), None
    )
    state.git_confiding = GitConfidingService(
        portal.pool, secrets, state.identity, catalog, utc_now
    )
    # Copies de travail dans un dossier jetable propre à l'exécution, comme le volume en service.
    volume = Path(tempfile.mkdtemp(prefix="miles-it-workdirs-"))
    workdirs = WorkDirs(volume)
    holds = HoldSpaces(volume / HOLDS_DIR)
    state.workspaces = WorkspacesService(
        portal.pool, resolver, catalog, utc_now, workdirs, holds, hosts
    )
    state.git_identities = GitIdentitiesService(
        portal.pool, cipher, httpx.AsyncClient(), catalog, utc_now, hosts
    )
    branches = WorkBranches(
        portal.pool, state.workspaces, resolver, workdirs, holds, state.git_identities, hosts
    )
    state.data_models = DataModelsService(portal.pool, branches, catalog, utc_now)
    state.domains = DomainsService(portal.pool, branches, catalog, utc_now)
    state.workshop = WorkshopService(portal.pool, branches, catalog, utc_now)
    state.contracts = ContractsService(portal.pool, branches, catalog, utc_now)
    state.contract_models = ContractModelsService(portal.pool, branches, catalog, utc_now)
    # Sans connexion ouverte tant que rien n'est lu : les tests n'y font passer que des
    # adresses refusées avant toute requête.
    state.remote_contracts = RemoteContracts(httpx.AsyncClient())
    state.branches = BranchesService(portal.pool, branches, catalog, utc_now)
    state.branch_holds = BranchHoldsService(portal.pool, branches, catalog, utc_now)
    state.shelves = ShelvesService(portal.pool, branches, catalog, utc_now)
    state.template_catalog = CatalogService(branches)
    state.targeted_reads = TargetedReads(branches)
    state.chains = ChainsService(portal.pool, branches, catalog, utc_now)
    state.sources = SourcesService(portal.pool, branches, catalog, utc_now)
    state.storages = StoragesService(portal.pool, branches, catalog, utc_now)
    state.workspace_cultures = WorkspaceCulturesService(portal.pool, branches, catalog, utc_now)
    state.api_keys = ApiKeysService(portal.pool, catalog, utc_now)
    # Celui de la configuration par défaut : l'essai d'une chaîne s'évalue sous cette borne.
    state.transform_budget = Settings.model_fields["transform_budget"].default
    state.actor_identities = ActorIdentitiesService(portal.pool, utc_now)
    state.public_url = None
    state.oauth_clients = OAuthClientsService(portal.pool, catalog, utc_now)
    # Sans adresse publique, comme une instance sans MILES_PUBLIC_URL : OAuth fermé.
    state.oauth_flow = OAuthFlow(portal.pool, state.oauth_clients, catalog, utc_now, None)
    state.oauth_access = OAuthAccess(portal.pool, state.auth.store, catalog, utc_now)


async def add_secret(client: httpx.AsyncClient, slug: str, kind: str, value: str) -> None:
    body = {"slug": slug, "label": slug, "secret_type": kind, "value": value}
    assert (await client.post("/api/secrets", json=body)).status_code == 201


async def add_connection(client: httpx.AsyncClient, cid: str, base: str, **access: object) -> None:
    body = {"id": cid, "label": cid, "base_url": base} | access
    created = await client.post("/api/git-connections", json=body)
    assert created.status_code == 201, created.text


async def create_workspace(client: httpx.AsyncClient, wid: str = "retrait") -> httpx.Response:
    body = {"id": wid, "name": f"Nom {wid}", "default_culture": "en-US"}
    return await client.post("/api/workspaces", json=body)


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
