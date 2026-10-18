from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import structlog
from fastapi import FastAPI

from miles.api_health import router as health_router
from miles.config import Settings
from miles.db.migration_files import file_load_migrations
from miles.db.pool import db_create_pool
from miles.health import resolve_health
from miles.log_config import configure_logging

log = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    """Fabrique appelée par uvicorn (`--factory`) : la configuration est lue au démarrage."""
    settings = Settings()  # type: ignore[call-arg]  # valeurs lues dans l'environnement
    configure_logging(settings.log_level)
    # La version attendue vient des fichiers embarqués dans l'image : c'est ce que
    # ce code sait servir, et la base doit l'avoir atteinte.
    expected_version = file_load_migrations(settings.migrations_dir)[-1].version

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = await db_create_pool(settings)
        app.state.health_probe = partial(
            resolve_health, pool, expected_version, settings.db_connect_timeout_s
        )
        log.info("demarrage", expected_schema_version=expected_version)
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title="Miles", lifespan=lifespan)
    app.include_router(health_router)
    return app
