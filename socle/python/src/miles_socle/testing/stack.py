"""Montage d'un produit sur une base réelle, sans passer par uvicorn.

Les sept services du socle sont câblés ICI, une fois, pour les trois produits. Écueil payé
deux fois dans le portail (LESSONS.md, 22 puis 24/10/2026) : un service ajouté à
l'application et oublié dans le montage de test fait tomber tous les tests d'intégration de
ce service, pour une raison qui n'a rien à voir avec lui. Avec trois produits, c'était trois
endroits où l'oubli était possible ; il n'en reste qu'un, et `wiring.py` porte la garde qui
le rend visible.

Le produit n'est pas importé : son `build_app`, son répertoire de migrations et ses types
d'events arrivent par INJECTION. Le socle qui les importerait importerait un produit, et le
test de frontière passerait au rouge — à juste titre.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
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
from miles_socle.testing.files import ADMIN_USERNAME, BASE_ENV, admin_env, write_env

HEALTH_TIMEOUT_S = 5.0


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SocleStack:
    """Base migrée, application câblée comme en production, et un client connecté.

    `cipher` et `catalog` sont rendus parce qu'un produit en a besoin pour câbler SES
    propres services dans la même transaction de montage — l'environnement s'en sert pour
    son service d'identité. Les redonner évite qu'il les reconstruise autrement.
    """

    pool: asyncpg.Pool
    app: FastAPI
    client: httpx.AsyncClient
    env_file: Path
    http: httpx.AsyncClient
    cipher: SecretCipher
    catalog: EventTypeCatalog
    base_url: str

    def anonymous(self) -> httpx.AsyncClient:
        """Un client SANS session : l'état d'un visiteur, et celui d'un pair non authentifié."""
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=self.base_url
        )


@asynccontextmanager
async def open_socle_stack(
    *,
    dsn: str,
    tmp_path: Path,
    build_app: Callable[[], FastAPI],
    migrations_dir: Path,
    event_types: frozenset[str],
    base_url: str,
    public_url: str,
    admin_email: str | None,
    session_ttl: timedelta = timedelta(hours=1),
) -> AsyncIterator[SocleStack]:
    """Monte les services du socle sur une base réelle et rend un client administrateur.

    `admin_email=None` monte une installation NEUVE, sans administrateur : c'est l'état
    dans lequel l'écran d'amorçage est ouvert, et le seul où il l'est. Le client rendu n'a
    alors aucune session, puisqu'il n'y a personne à qui en ouvrir une.
    """
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    if pool is None:  # pragma: no cover - asyncpg type le retour optionnel, il ne l'est pas
        # Levé et non `assert` : un `assert` disparaît sous `python -O`, et le montage
        # continuerait alors avec None jusqu'à une erreur sans rapport.
        raise RuntimeError("asyncpg n'a pas rendu de pool")
    try:
        migrations = file_load_migrations(migrations_dir)
        async with pool.acquire() as conn:
            await resolve_apply_migrations(conn, migrations)
        env, backup = write_env(
            tmp_path, BASE_ENV if admin_email is None else admin_env(admin_email)
        )
        catalog = EventTypeCatalog(event_types)
        cipher = SecretCipher(bytes(range(32)))
        app = build_app()
        app.state.health_probe = lambda: resolve_health(
            pool, migrations[-1].version, HEALTH_TIMEOUT_S
        )
        store = AdminAccountStore.file_load(env, backup)
        app.state.auth = AuthContext(
            store=store,
            db=pool,
            throttle=LoginThrottle(),
            session_ttl=session_ttl,
            # Faux pour que le cookie traverse le transport ASGI des tests ; en production
            # il est vrai, et c'est l'attribut Domain — toujours absent — qui porte
            # l'étanchéité entre produits.
            cookie_secure=False,
        )
        app.state.secrets = SecretsService(pool, cipher, catalog, utc_now)
        app.state.cultures = CulturesService(pool, catalog, utc_now)
        # Après les cultures, et pas avant : les préférences les reçoivent. Les intervertir
        # ne casse pas à la construction, seulement à l'exécution.
        app.state.preferences = PreferencesService(pool, app.state.cultures, utc_now)
        async with httpx.AsyncClient() as http:
            app.state.oidc = OidcService(
                pool,
                http,
                app.state.secrets,
                catalog,
                utc_now,
                public_url,
                # Les tests d'intégration éprouvent le parcours contre un fournisseur
                # JETABLE servi en HTTP. En production ce drapeau est faux, et c'est une
                # garde : un fournisseur en HTTP laisse passer jetons et codes en clair.
                allow_http_issuer=True,
                admin_email=lambda: store.account.email if store.account else None,
            )
            app.state.public_url = public_url
            cookies = {}
            if admin_email is not None:
                token, digest = new_session_token()
                await db_create_session(
                    pool, digest, LOCAL_ADMIN_KIND, ADMIN_USERNAME, utc_now() + session_ttl
                )
                cookies = {SESSION_COOKIE: token}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=base_url, cookies=cookies
            ) as client:
                yield SocleStack(pool, app, client, env, http, cipher, catalog, base_url)
    finally:
        await pool.close()
