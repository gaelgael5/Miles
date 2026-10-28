"""Montage d'un produit sur une base réelle, sans passer par uvicorn.

Les sept services du socle sont câblés par `wire_socle_services` — LA MÊME fonction que
celle qu'appelle `app.py` en production. C'est ce qui rend impossible, et non plus
seulement improbable, l'oubli d'un service du socle ici : il n'y a plus deux listes à
tenir d'accord. Écueil payé deux fois dans le portail (LESSONS.md, 22 puis 24/10/2026) —
un service ajouté à l'application et oublié dans le montage faisait tomber tous les tests
de ce service, sur une erreur qui ne parlait pas de lui. `wiring.py` garde ce qui reste :
les services PROPRES à un produit, que le socle ne connaît pas.

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

from miles_socle.app_state import wire_socle_services
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.sessions import (
    LOCAL_ADMIN_KIND,
    SESSION_COOKIE,
    db_create_session,
    new_session_token,
)
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.testing.files import ADMIN_USERNAME, BASE_ENV, admin_env, write_env

HEALTH_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class TestRuntime:
    """La configuration du montage de test, à la forme que `wire_socle_services` attend.

    Trois valeurs diffèrent de la production, et chacune pour une raison :

    - `cookie_secure=False`, sans quoi le cookie ne traverse pas le transport ASGI des
      tests. En production il est vrai, et c'est l'attribut `Domain` — toujours absent —
      qui porte l'étanchéité entre produits ;
    - `allow_http_identity_providers=True`, parce que la campagne éprouve le parcours
      contre un fournisseur JETABLE servi en HTTP. En production c'est une garde : un
      fournisseur en HTTP laisse passer jetons et codes en clair ;
    - une session d'une heure, qui suffit à un test et n'a pas à durer douze heures.
    """

    public_url: str | None
    session_ttl_s: int
    cookie_secure: bool = False
    allow_http_identity_providers: bool = True
    db_connect_timeout_s: float = HEALTH_TIMEOUT_S


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
        store = AdminAccountStore.file_load(env, backup)
        async with httpx.AsyncClient() as http:
            # La MÊME fonction que celle qu'appelle `app.py` : il n'y a plus deux listes de
            # services à tenir d'accord.
            wire_socle_services(
                app,
                settings=TestRuntime(
                    public_url=public_url, session_ttl_s=int(session_ttl.total_seconds())
                ),
                pool=pool,
                store=store,
                cipher=cipher,
                catalog=catalog,
                http=http,
                expected_schema_version=migrations[-1].version,
                now=utc_now,
            )
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
