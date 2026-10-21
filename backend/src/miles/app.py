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
from miles.auth.admin_store import AdminAccountStore
from miles.auth.api_auth import router as auth_router
from miles.auth.context import AuthContext, utc_now
from miles.auth.gate import auth_gate
from miles.auth.throttle import LoginThrottle
from miles.config import Settings
from miles.cultures import service as cultures_events
from miles.cultures.api_cultures import public_router as login_cultures_router
from miles.cultures.api_cultures import router as cultures_router
from miles.cultures.service import CulturesService
from miles.db.migration_files import file_load_migrations
from miles.db.pool import db_create_pool
from miles.events.model import EventTypeCatalog
from miles.health import resolve_health
from miles.log_config import configure_logging
from miles.mqtt.protocol import BUILTIN_HANDLERS
from miles.mqtt.responder import MqttSettings, run_responder
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
        app.state.workspaces = WorkspacesService(
            pool,
            app.state.secrets,
            catalog,
            utc_now,
            tuple(settings.git_test_hosts),
            settings.git_test_ca_file,
        )
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
    return app
