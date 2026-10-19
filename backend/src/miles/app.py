from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from functools import partial

import structlog
from fastapi import FastAPI

from miles.api_health import router as health_router
from miles.auth.admin_store import AdminAccountStore
from miles.auth.api_auth import router as auth_router
from miles.auth.context import AuthContext
from miles.auth.gate import auth_gate
from miles.auth.throttle import LoginThrottle
from miles.config import Settings
from miles.db.migration_files import file_load_migrations
from miles.db.pool import db_create_pool
from miles.health import resolve_health
from miles.log_config import configure_logging
from miles.mqtt.protocol import BUILTIN_HANDLERS
from miles.mqtt.responder import MqttSettings, run_responder

log = structlog.get_logger(__name__)
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
    return app
