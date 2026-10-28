from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from functools import partial

import httpx
import structlog
from fastapi import FastAPI
from fastapi.routing import APIRoute
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.api_auth import router as auth_router
from miles_socle.auth.api_preferences import PreferencesService
from miles_socle.auth.api_preferences import router as preferences_router
from miles_socle.auth.context import AuthContext, utc_now
from miles_socle.auth.gate import auth_gate
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.cultures.api_cultures import public_router as login_cultures_router
from miles_socle.cultures.api_cultures import router as cultures_router
from miles_socle.cultures.service import CulturesService
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.pool import db_create_pool
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.api_health import router as health_router
from miles_socle.health.probe import resolve_health
from miles_socle.log_config import configure_logging
from miles_socle.oidc.api_connectors import router as oidc_connectors_router
from miles_socle.oidc.api_login import router as oidc_login_router
from miles_socle.oidc.service import OidcService
from miles_socle.secrets.api_secrets import router as secrets_router
from miles_socle.secrets.api_secrets import types_router as secret_types_router
from miles_socle.secrets.crypto import SecretCipher, parse_secrets_key
from miles_socle.secrets.service import SecretsService

from environnement.config import Settings
from environnement.event_types import code_event_types
from environnement.identity.api_identity import router as identity_router
from environnement.identity.api_peer import router as peer_router
from environnement.identity.service import IdentityService

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
    catalog = EventTypeCatalog(code_event_types())

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
        # Aucune écriture ici, et aucune lecture de ses tables : la paire de clés est
        # engendrée au PREMIER USAGE. `dev-deploy.sh` lance la stack avant de jouer les
        # migrations, donc sur une base neuve rien de ce schéma n'existe encore au
        # démarrage — un composant qui l'exigerait tomberait en boucle de redémarrage et
        # emporterait la migration avec lui (mesuré le 28/10/2026, voir le service).
        app.state.identity = IdentityService(
            pool,
            app.state.secrets,
            cipher,
            catalog,
            utc_now,
            http,
            settings.public_url,
        )
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
        app.state.public_url = settings.public_url
        log.info(
            "demarrage",
            expected_schema_version=expected_version,
            admin_declared=store.account is not None,
        )
        try:
            yield
        finally:
            await http.aclose()
            await pool.close()

    return build_app(lifespan)


def build_app(lifespan: Lifespan | None = None) -> FastAPI:
    """Routes et passerelle d'authentification, sans dépendance à l'environnement."""
    # Pas de /docs ni d'/openapi.json servis : ce seraient des routes ouvertes
    # hors de la passerelle d'authentification. La spec se génère par app.openapi().
    app = FastAPI(
        title="Miles — module d'environnement",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Fail closed : la passerelle n'ouvre qu'une liste blanche de routes publiques, et
    # toute route /api ajoutée demain exige donc une session sans que personne y pense.
    app.middleware("http")(auth_gate)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(secrets_router)
    app.include_router(secret_types_router)
    app.include_router(cultures_router)
    app.include_router(login_cultures_router)
    app.include_router(oidc_connectors_router)
    app.include_router(oidc_login_router)
    app.include_router(preferences_router)
    app.include_router(identity_router)
    # Routes authentifiées par SIGNATURE, et le portillon ne les laisse passer que parce
    # qu'elles le sont. La liste est DÉRIVÉE du routeur qui les porte, jamais retapée :
    # un chemin ouvert à côté de sa vérification serait ouvert à tous, et c'est
    # exactement l'erreur que cette dérivation rend inexprimable.
    app.include_router(peer_router)
    app.state.signed_api_paths = frozenset(
        route.path for route in peer_router.routes if isinstance(route, APIRoute)
    )
    return app
