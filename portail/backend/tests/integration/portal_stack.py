from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.sessions import (
    LOCAL_ADMIN_KIND,
    SESSION_COOKIE,
    db_create_session,
    new_session_token,
)
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.testing.files import admin_env, write_env
from miles_socle.testing.stack import utc_now

from miles.app import build_app
from miles.config import DEFAULT_MIGRATIONS_DIR

# Réexporté : `git_stack` et une dizaine de fichiers de test prennent `utc_now` ici.
__all__ = ["PortalStack", "open_portal_stack", "utc_now"]


@dataclass
class PortalStack:
    """Base migrée, application, et un client porteur d'une session administrateur."""

    pool: asyncpg.Pool
    app: FastAPI
    client: httpx.AsyncClient

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://miles"
        )


@asynccontextmanager
async def open_portal_stack(
    dsn: str, tmp_path: Path, admin_email: str = "admin@miles.invalid"
) -> AsyncIterator[PortalStack]:
    """Montage MINIMAL : la base migrée, le compte d'amorçage, une session administrateur.

    Divergence VOLONTAIRE avec les deux autres produits, qui emploient `open_socle_stack`
    et obtiennent les sept services du socle d'un coup. Ici, chaque test câble ce dont il a
    besoin, avec ses propres doublures et son propre catalogue d'events — c'est le style de
    cette suite, et une quinzaine de fichiers s'y appuient. Pré-câbler les sept services
    changerait ce que ces tests observent, et un refactoring ne réécrit pas les tests.

    Ce qui est partagé avec le socle l'est quand même : la base jetable, la forme du `.env`,
    le compte d'amorçage et son empreinte, l'horloge. Et la garde de `test_cablage_pg.py`
    lit TOUS les fichiers de la suite d'intégration, donc les services câblés dans un test
    comptent — ce qui rend la divergence sans conséquence pour elle.
    """
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        env, backup = write_env(tmp_path, admin_env(admin_email))
        app = build_app()
        app.state.auth = AuthContext(
            store=AdminAccountStore.file_load(env, backup),
            db=pool,
            throttle=LoginThrottle(),
            session_ttl=timedelta(hours=1),
            cookie_secure=False,
        )
        token, digest = new_session_token()
        expires = utc_now() + timedelta(hours=1)
        await db_create_session(pool, digest, LOCAL_ADMIN_KIND, "admin", expires)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://miles",
            cookies={SESSION_COOKIE: token},
        ) as client:
            yield PortalStack(pool, app, client)
    finally:
        await pool.close()
