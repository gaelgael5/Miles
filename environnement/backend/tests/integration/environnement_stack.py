from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.api_preferences import PreferencesService
from miles_socle.auth.context import AuthContext
from miles_socle.auth.passwords import hash_password
from miles_socle.auth.sessions import (
    LOCAL_ADMIN_KIND,
    SESSION_COOKIE,
    db_create_session,
    new_session_token,
)
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.cultures.service import CulturesService
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.probe import resolve_health
from miles_socle.oidc.service import OidcService
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService

from environnement.app import build_app
from environnement.config import DEFAULT_MIGRATIONS_DIR
from environnement.event_types import code_event_types
from environnement.identity.service import IdentityService

# Ni le mot de passe ni les entrées de ce .env n'ont de valeur hors des tests : ce sont
# des formes, destinées à vérifier que le produit ne les écrase pas.
BASE_ENV = "MILES_DB_PASSWORD=ne-pas-toucher\nMILES_HTTP_PORT=8182\n"
ADMIN_PASSWORD = "correct horse battery"
ADMIN_USERNAME = "admin"


def utc_now() -> datetime:
    return datetime.now(UTC)


def write_env(tmp_path: Path, content: str = BASE_ENV) -> tuple[Path, Path]:
    """.env et .env.bak tels que dev-deploy.sh les prépare : les deux existent."""
    env, backup = tmp_path / ".env", tmp_path / ".env.bak"
    env.write_text(content, encoding="utf-8")
    env.chmod(0o600)
    backup.write_text("", encoding="utf-8")
    backup.chmod(0o600)
    return env, backup


def admin_env(email: str) -> str:
    return (
        BASE_ENV
        + f"MILES_ADMIN_EMAIL='{email}'\nMILES_ADMIN_USERNAME='{ADMIN_USERNAME}'\n"
        + f"MILES_ADMIN_PASSWORD_HASH='{hash_password(ADMIN_PASSWORD)}'\n"
    )


@dataclass
class EnvironnementStack:
    """Base migrée, application câblée comme en production, et un client connecté."""

    pool: asyncpg.Pool
    app: FastAPI
    client: httpx.AsyncClient
    env_file: Path
    http: httpx.AsyncClient
    identity: IdentityService

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://environnement"
        )


@asynccontextmanager
async def open_stack(
    dsn: str,
    tmp_path: Path,
    *,
    admin_email: str | None = "admin@environnement.invalid",
    public_url: str = "http://environnement.test",
    peer_app: FastAPI | None = None,
) -> AsyncIterator[EnvironnementStack]:
    """Monte le produit sur une base réelle, sans passer par uvicorn.

    Les services sont câblés ICI comme dans `create_app`. Écueil payé dans le portail
    (LESSONS.md, 22 puis 24/10/2026) : un service ajouté à l'application et oublié dans
    ce montage fait tomber tous les tests d'intégration du service, pour une raison qui
    n'a rien à voir avec lui. Après tout ajout à `app.py`, vérifier ici.

    `admin_email=None` monte une installation NEUVE, sans administrateur : c'est l'état
    dans lequel l'écran d'amorçage est ouvert, et le seul où il l'est.

    `peer_app` remplace le réseau par une contrepartie EN PROCESSUS pour les appels
    sortants vers le pair. En production, le service de l'identité partage le client HTTP
    de l'OIDC ; ici il en reçoit un dont le transport mène à la contrepartie, parce que le
    pair est l'AUTRE produit : son côté du protocole s'écrit avec le ticket 6a0daab6, et
    ce qui existe aujourd'hui, c'est le vérificateur du socle — celui-là même qu'il
    emploiera.
    """
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        expected = file_load_migrations(DEFAULT_MIGRATIONS_DIR)[-1].version
        env, backup = write_env(
            tmp_path, BASE_ENV if admin_email is None else admin_env(admin_email)
        )
        catalog = EventTypeCatalog(code_event_types())
        app = build_app()
        app.state.health_probe = lambda: resolve_health(pool, expected, 5.0)
        store = AdminAccountStore.file_load(env, backup)
        app.state.auth = AuthContext(
            store=store,
            db=pool,
            throttle=LoginThrottle(),
            session_ttl=timedelta(hours=1),
            # Faux pour que le cookie traverse le transport ASGI des tests ; en
            # production il est vrai, et c'est l'attribut Domain — toujours absent —
            # qui porte l'étanchéité entre produits.
            cookie_secure=False,
        )
        cipher = SecretCipher(bytes(range(32)))
        app.state.secrets = SecretsService(pool, cipher, catalog, utc_now)
        app.state.cultures = CulturesService(pool, catalog, utc_now)
        app.state.preferences = PreferencesService(pool, app.state.cultures, utc_now)
        async with httpx.AsyncClient() as http:
            app.state.oidc = OidcService(
                pool,
                http,
                app.state.secrets,
                catalog,
                utc_now,
                public_url,
                allow_http_issuer=True,
                admin_email=lambda: store.account.email if store.account else None,
            )
            app.state.public_url = public_url
            transport = None if peer_app is None else httpx.ASGITransport(app=peer_app)
            cookies = {}
            if admin_email is not None:
                token, digest = new_session_token()
                await db_create_session(
                    pool, digest, LOCAL_ADMIN_KIND, ADMIN_USERNAME, utc_now() + timedelta(hours=1)
                )
                cookies = {SESSION_COOKIE: token}
            async with (
                httpx.AsyncClient(transport=transport) as peer_http,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://environnement",
                    cookies=cookies,
                ) as client,
            ):
                identity = IdentityService(
                    pool, app.state.secrets, cipher, catalog, utc_now, peer_http, public_url
                )
                app.state.identity = identity
                # Rien n'est engendré ici, et c'est fidèle au démarrage réel : l'identité
                # naît au premier USAGE. Un montage qui la créerait d'avance cacherait
                # justement le cas que la machine de test a révélé.
                yield EnvironnementStack(pool, app, client, env, http, identity)
    finally:
        await pool.close()
