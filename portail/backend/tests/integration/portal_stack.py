from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI

from miles.app import build_app
from miles.auth.admin_store import AdminAccountStore
from miles.auth.context import AuthContext
from miles.auth.passwords import hash_password
from miles.auth.sessions import (
    LOCAL_ADMIN_KIND,
    SESSION_COOKIE,
    db_create_session,
    new_session_token,
)
from miles.auth.throttle import LoginThrottle
from miles.config import DEFAULT_MIGRATIONS_DIR
from miles.db.migration_files import file_load_migrations
from miles.db.migrations import resolve_apply_migrations
from tests.auth_fixtures import ADMIN_PASSWORD, BASE_ENV, write_env


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        env, backup = write_env(
            tmp_path,
            BASE_ENV
            + f"MILES_ADMIN_EMAIL='{admin_email}'\nMILES_ADMIN_USERNAME='admin'\n"
            + f"MILES_ADMIN_PASSWORD_HASH='{hash_password(ADMIN_PASSWORD)}'\n",
        )
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
