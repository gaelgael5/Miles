from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from functools import partial

import httpx
import structlog
from fastapi import FastAPI

from miles.api_health import router as health_router
from miles.apikeys import service as apikeys_events
from miles.apikeys.api_apikeys import router as api_keys_router
from miles.apikeys.service import ApiKeysService
from miles.auth.admin_store import AdminAccountStore
from miles.auth.api_auth import router as auth_router
from miles.auth.api_preferences import PreferencesService
from miles.auth.api_preferences import router as preferences_router
from miles.auth.context import AuthContext, utc_now
from miles.auth.gate import auth_gate
from miles.auth.throttle import LoginThrottle
from miles.chains import service as chains_events
from miles.chains.api_chains import router as chains_api_router
from miles.chains.service import ChainsService
from miles.config import Settings
from miles.contracts import service as contracts_events
from miles.contracts.api_contracts import router as contracts_router
from miles.contracts.remote import RemoteContracts
from miles.contracts.service import ContractsService
from miles.cultures import service as cultures_events
from miles.cultures.api_cultures import public_router as login_cultures_router
from miles.cultures.api_cultures import router as cultures_router
from miles.cultures.service import CulturesService
from miles.datamodels import service as datamodels_events
from miles.datamodels.api_datamodels import router as data_models_router
from miles.datamodels.service import DataModelsService
from miles.db.migration_files import file_load_migrations
from miles.db.pool import db_create_pool
from miles.events.model import EventTypeCatalog
from miles.git.holdspace import HOLDS_DIR, HoldSpaces
from miles.git.workdirs import WorkDirs
from miles.gitaccess import model as gitaccess_events
from miles.gitaccess.api_gitaccess import connections_router
from miles.gitaccess.connections import ConnectionsService
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.resolver import AccessResolver
from miles.health import resolve_health
from miles.identities import service as identities_events
from miles.identities.api_identities import router as identities_router
from miles.identities.service import GitIdentitiesService
from miles.log_config import configure_logging
from miles.mcp_api.server import MCP_MOUNT, MCP_PATH, build_server, mcp_app
from miles.mqtt.protocol import BUILTIN_HANDLERS
from miles.mqtt.responder import MqttSettings, run_responder
from miles.oauth import clients as oauth_events
from miles.oauth.access import OAuthAccess
from miles.oauth.api_authorize import router as oauth_authorize_router
from miles.oauth.api_clients import router as oauth_clients_router
from miles.oauth.api_public import router as oauth_public_router
from miles.oauth.clients import OAuthClientsService
from miles.oauth.flow import OAuthFlow
from miles.obo.api_identity import router as identity_router
from miles.obo.service import ActorIdentitiesService
from miles.oidc import service as oidc_events
from miles.oidc.api_connectors import router as oidc_connectors_router
from miles.oidc.api_login import router as oidc_login_router
from miles.oidc.service import OidcService
from miles.secrets import service as secrets_events
from miles.secrets.api_secrets import router as secrets_router
from miles.secrets.api_secrets import types_router as secret_types_router
from miles.secrets.crypto import SecretCipher, parse_secrets_key
from miles.secrets.service import SecretsService
from miles.security import service as security_events
from miles.security.api_security import router as security_router
from miles.security.service import SecurityServices
from miles.sources import service as sources_events
from miles.sources.api_sources import router as sources_router
from miles.sources.service import SourcesService
from miles.transform.api_catalog import CatalogService
from miles.transform.api_catalog import router as catalog_router
from miles.transform.api_transform import chains_router
from miles.transform.api_transform import router as transform_router
from miles.workshop import branches as branches_events
from miles.workshop import holds as holds_events
from miles.workshop import service as workshop_events
from miles.workshop.api_branches import router as branches_router
from miles.workshop.api_branches import views_router as branch_views_router
from miles.workshop.api_holds import router as holds_router
from miles.workshop.api_workshop import router as workshop_router
from miles.workshop.branches import BranchesService
from miles.workshop.holds import BranchHoldsService
from miles.workshop.service import WorkshopService
from miles.workshop.target import WorkBranches
from miles.workspaces import model as workspace_events
from miles.workspaces.api_workspaces import router as workspaces_router
from miles.workspaces.service import WorkspacesService

log = structlog.get_logger(__name__)
# Un fournisseur lent ne doit pas retenir un utilisateur indéfiniment sur la connexion.
OIDC_HTTP_TIMEOUT_S = 5.0
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app() -> FastAPI:
    """Fabrique appelée par uvicorn (`--factory`) : la configuration est lue au démarrage."""
    settings = Settings()  # type: ignore[call-arg]  # valeurs lues dans l'environnement
    configure_logging(settings.log_level)
    # La version attendue vient des fichiers embarqués dans l'image : c'est ce que
    # ce code sait servir, et la base doit l'avoir atteinte.
    expected_version = file_load_migrations(settings.migrations_dir)[-1].version
    # Lu avant tout : un .env illisible ou un compte partiel empêche le démarrage
    # (fail closed) au lieu d'ouvrir l'amorçage au premier venu.
    store = AdminAccountStore.file_load(settings.env_file, settings.env_backup_file)
    # Même règle pour la clé des secrets : absente ou mal formée, on ne démarre pas.
    cipher = SecretCipher(parse_secrets_key(settings.secrets_key.get_secret_value()))
    # Catalogue des types d'event connus du code. Le catalogue déclaré dans git
    # viendra avec son propre ticket ; d'ici là, chaque module apporte ses types.
    catalog = EventTypeCatalog(
        secrets_events.EVENT_TYPES
        | cultures_events.EVENT_TYPES
        | oidc_events.EVENT_TYPES
        | security_events.EVENT_TYPES
        | workspace_events.EVENT_TYPES
        | gitaccess_events.EVENT_TYPES
        | datamodels_events.EVENT_TYPES
        | workshop_events.EVENT_TYPES
        | contracts_events.EVENT_TYPES
        | branches_events.EVENT_TYPES
        | holds_events.EVENT_TYPES
        | identities_events.EVENT_TYPES
        | chains_events.EVENT_TYPES
        | sources_events.EVENT_TYPES
        | apikeys_events.EVENT_TYPES
        | oauth_events.EVENT_TYPES
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = await db_create_pool(settings)
        app.state.health_probe = partial(
            resolve_health, pool, expected_version, settings.db_connect_timeout_s
        )
        app.state.auth = AuthContext(
            store=store,
            db=pool,
            throttle=LoginThrottle(),
            session_ttl=timedelta(seconds=settings.session_ttl_s),
            cookie_secure=settings.cookie_secure,
        )
        app.state.secrets = SecretsService(pool, cipher, catalog, utc_now)
        app.state.cultures = CulturesService(pool, catalog, utc_now)
        app.state.preferences = PreferencesService(pool, app.state.cultures, utc_now)
        # Pas de redirection suivie : un fournisseur qui redirige la découverte ou
        # l'échange de code ne doit pas nous emmener ailleurs sans qu'on le voie.
        http = httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT_S, follow_redirects=False)
        app.state.oidc = OidcService(
            pool,
            http,
            app.state.secrets,
            catalog,
            utc_now,
            settings.public_url,
            settings.allow_http_identity_providers,
            admin_email=lambda: store.account.email if store.account else None,
        )
        app.state.security = SecurityServices(
            pool, http, app.state.secrets, catalog, utc_now, settings.allow_http_identity_providers
        )
        git_hosts = tuple(settings.git_test_hosts)
        resolver = AccessResolver(app.state.secrets)
        verifier = DependentsVerifier(pool, catalog, utc_now, git_hosts)
        app.state.git_connections = ConnectionsService(
            pool, resolver, verifier, catalog, utc_now, git_hosts
        )
        app.state.workspaces = WorkspacesService(pool, resolver, catalog, utc_now, git_hosts)
        app.state.git_identities = GitIdentitiesService(
            pool, cipher, http, catalog, utc_now, git_hosts
        )
        workdirs = WorkDirs(settings.workcopies_dir)
        # Espaces de prise de main sur le même volume, à part des copies de lecture : un
        # identifiant de workspace ne commence jamais par « _ », aucun ne s'y confond.
        holds = HoldSpaces(settings.workcopies_dir / HOLDS_DIR)
        branches = WorkBranches(
            pool,
            app.state.workspaces,
            resolver,
            workdirs,
            holds,
            app.state.git_identities,
            git_hosts,
        )
        app.state.data_models = DataModelsService(pool, branches, catalog, utc_now)
        app.state.workshop = WorkshopService(pool, branches, catalog, utc_now)
        app.state.contracts = ContractsService(pool, branches, catalog, utc_now)
        app.state.remote_contracts = RemoteContracts(http)
        app.state.transform_budget = settings.transform_budget
        app.state.branches = BranchesService(pool, branches, catalog, utc_now)
        app.state.branch_holds = BranchHoldsService(pool, branches, catalog, utc_now)
        app.state.template_catalog = CatalogService(branches)
        app.state.chains = ChainsService(pool, branches, catalog, utc_now)
        app.state.sources = SourcesService(pool, branches, catalog, utc_now)
        app.state.api_keys = ApiKeysService(pool, catalog, utc_now)
        app.state.public_url = settings.public_url
        app.state.oauth_clients = OAuthClientsService(pool, catalog, utc_now)
        # Ressource annoncée et exigée : l'adresse publique de /mcp/, ou rien si elle manque.
        resource = None if settings.public_url is None else settings.public_url + MCP_PATH
        app.state.oauth_flow = OAuthFlow(pool, app.state.oauth_clients, catalog, utc_now, resource)
        app.state.oauth_access = OAuthAccess(pool, store, catalog, utc_now)
        app.state.actor_identities = ActorIdentitiesService(pool, utc_now)
        responder = asyncio.create_task(
            run_responder(
                MqttSettings(
                    host=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username,
                    password=settings.mqtt_password,
                    client_id=f"miles-backend-{socket.gethostname()}",
                ),
                BUILTIN_HANDLERS,
            )
        )
        # Le service MQTT tourne en tâche de fond : s'il s'arrête sur une erreur
        # imprévue, le journal doit le dire au lieu de laisser les terminaux sans réponse.
        responder.add_done_callback(_log_responder_end)
        log.info(
            "demarrage",
            expected_schema_version=expected_version,
            admin_declared=store.account is not None,
        )
        try:
            # Le gestionnaire de sessions MCP vit avec l'app hôte : la durée de vie d'une
            # sous-application montée ne s'exécute jamais.
            async with app.state.mcp.session_manager.run():
                yield
        finally:
            responder.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await responder
            await http.aclose()
            await pool.close()

    return build_app(lifespan)


def _log_responder_end(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("mqtt_service_arrete", reason=repr(task.exception()))


def build_app(lifespan: Lifespan | None = None) -> FastAPI:
    """Routes et passerelle d'authentification, sans dépendance à l'environnement."""
    # Pas de /docs ni d'/openapi.json servis : ce seraient des routes ouvertes
    # hors de la passerelle d'authentification. La spec se génère par app.openapi().
    app = FastAPI(title="Miles", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.middleware("http")(auth_gate)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(secrets_router)
    app.include_router(secret_types_router)
    app.include_router(cultures_router)
    app.include_router(login_cultures_router)
    app.include_router(oidc_connectors_router)
    app.include_router(oidc_login_router)
    app.include_router(security_router)
    app.include_router(workspaces_router)
    app.include_router(connections_router)
    app.include_router(data_models_router)
    app.include_router(workshop_router)
    app.include_router(contracts_router)
    app.include_router(branches_router)
    app.include_router(branch_views_router)
    app.include_router(holds_router)
    app.include_router(preferences_router)
    app.include_router(identities_router)
    app.include_router(transform_router)
    app.include_router(chains_router)
    app.include_router(catalog_router)
    app.include_router(chains_api_router)
    app.include_router(sources_router)
    app.include_router(api_keys_router)
    app.include_router(identity_router)
    app.include_router(oauth_clients_router)
    app.include_router(oauth_authorize_router)
    app.include_router(oauth_public_router)
    # Surface MCP (story 0d4e4f75) : hors /api, donc hors de la passerelle des sessions ;
    # gardée par sa propre clé. Adresse publiée : /mcp/.
    app.state.mcp = build_server()
    app.mount(MCP_MOUNT, mcp_app(app.state.mcp))
    return app
