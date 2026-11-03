from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.routing import APIRoute
from miles_socle.app_state import wire_socle_services
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.api_auth import router as auth_router
from miles_socle.auth.api_preferences import router as preferences_router
from miles_socle.auth.context import utc_now
from miles_socle.auth.gate import auth_gate
from miles_socle.cultures.api_cultures import public_router as login_cultures_router
from miles_socle.cultures.api_cultures import router as cultures_router
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.pool import db_create_pool
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.api_health import router as health_router
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.journal.api_journal import router as journal_router
from miles_socle.log_config import configure_logging
from miles_socle.oidc.api_connectors import router as oidc_connectors_router
from miles_socle.oidc.api_login import router as oidc_login_router
from miles_socle.secrets.api_secrets import router as secrets_router
from miles_socle.secrets.api_secrets import types_router as secret_types_router
from miles_socle.secrets.crypto import SecretCipher, parse_secrets_key

from enrolement.config import Settings
from enrolement.environments.api_environments import router as environments_router
from enrolement.environments.service import EnvironmentService
from enrolement.event_types import code_event_types
from enrolement.hosting.api_hosting import router as hosting_router
from enrolement.hosting.api_peer_hosting import router as peer_hosting_router
from enrolement.hosting.gitcache import HostingCache
from enrolement.hosting.relay import HostingRelay
from enrolement.hosting.service import HostingService
from enrolement.pairing.api_confided_git import router as confided_git_router
from enrolement.pairing.api_pairing import router as pairing_router
from enrolement.pairing.api_peer import router as peer_router
from enrolement.pairing.service import PairingService

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
        # Pas de redirection suivie : un fournisseur qui redirige la découverte ou
        # l'échange de code ne doit pas nous emmener ailleurs sans qu'on le voie. Construit
        # ici parce que c'est l'appelant qui le ferme, à la sortie de la durée de vie.
        http = httpx.AsyncClient(timeout=OIDC_HTTP_TIMEOUT_S, follow_redirects=False)
        # Les sept services du socle, câblés par le socle : la MÊME fonction que celle
        # qu'appelle le harnais des tests d'intégration. Il n'y a plus deux listes à tenir
        # d'accord, et l'ordre de création — les préférences reçoivent les cultures —
        # n'est plus écrit qu'une fois.
        wire_socle_services(
            app,
            settings=settings,
            pool=pool,
            store=store,
            cipher=cipher,
            catalog=catalog,
            http=http,
            expected_schema_version=expected_version,
        )
        # Puis ce que CE produit ajoute. Aucune écriture ici, et aucune lecture de ses
        # tables : la paire de clés est engendrée au PREMIER USAGE. `dev-deploy.sh` lance la
        # stack avant de jouer les migrations, donc sur une base neuve rien de ce schéma
        # n'existe encore au démarrage — un composant qui l'exigerait tomberait en boucle de
        # redémarrage et emporterait la migration avec lui (mesuré le 28/10/2026).
        app.state.pairing = PairingService(
            pool,
            app.state.secrets,
            cipher,
            catalog,
            utc_now,
            settings.public_url,
            # Le MÊME client que l'OIDC : un seul pool de connexions sortantes pour ce
            # module, fermé par la durée de vie qui l'a ouvert.
            http,
            settings.pairing_request_ttl_s,
        )
        app.state.environments = EnvironmentService(pool, catalog, utc_now)
        app.state.hosting = HostingService(
            pool,
            cipher,
            catalog,
            utc_now,
            # La MÊME identité de module que l'appariement : c'est la clé privée de ce
            # module qui signe l'ordre poussé à l'environnement, et il n'en a qu'une.
            app.state.pairing.module,
            http,
            settings.public_url,
            HostingCache(settings.hosting_cache_dir),
            tuple(settings.git_test_hosts),
        )
        # Le relais tient le service plutôt que de l'étendre : il SERT du contenu là où
        # l'autre ORDONNE, et ce qui arrive chez lui est la demande d'un tiers.
        app.state.hosting_relay = HostingRelay(app.state.hosting)
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
        title="Miles — module d'enrôlement",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Fail closed : la passerelle n'ouvre qu'une liste blanche de routes publiques, et
    # toute route /api ajoutée demain exige donc une session sans que personne y pense.
    app.middleware("http")(auth_gate)
    app.include_router(health_router)
    # L'entretien des journaux partitionnés, appelé par un déclencheur d'HÔTE (décision du
    # 03/11/2026) : ni cookie ni personne derrière. Il vit dans /api et le portillon le
    # laisse passer par `system_api_paths` — déclaré ci-dessous DEPUIS le routeur qui le
    # porte, pour que le chemin et sa vérification ne puissent pas se séparer.
    app.include_router(journal_router)
    app.include_router(auth_router)
    app.include_router(secrets_router)
    app.include_router(secret_types_router)
    app.include_router(cultures_router)
    app.include_router(login_cultures_router)
    app.include_router(oidc_connectors_router)
    app.include_router(oidc_login_router)
    app.include_router(preferences_router)
    app.include_router(pairing_router)
    # Les connexions git confiées par le module de paramétrage : lecture seule, et servie
    # par le même service d'appariement — c'est l'appariement qui décide de ce qui est
    # détenu, et la cascade qui le détruit.
    app.include_router(confided_git_router)
    app.include_router(environments_router)
    app.include_router(hosting_router)
    # Routes authentifiées par SIGNATURE, et le portillon ne les laisse passer que parce
    # qu'elles le sont. La liste est DÉRIVÉE du routeur qui les porte, jamais retapée :
    # un chemin ouvert à côté de sa vérification serait ouvert à tous, et c'est
    # exactement l'erreur que cette dérivation rend inexprimable.
    app.include_router(peer_router)
    # Le relais de contenu est authentifié par signature lui aussi, et son routeur est à
    # part — l'autre est à sa limite de 300 lignes. Les DEUX entrent dans la liste
    # blanche, dérivée de ce que les routeurs portent : un chemin ouvert à côté de sa
    # vérification serait ouvert à tous, et cette dérivation rend l'oubli inexprimable.
    app.include_router(peer_hosting_router)
    # Une liste DISTINCTE de `signed_api_paths` : une signature prouve l'identité d'un
    # pair par une clé échangée à l'appariement, un secret de stack ne prouve que
    # l'appartenance à la stack. Les confondre laisserait un chemin déclaré pour l'un
    # s'ouvrir par le mécanisme de l'autre.
    app.state.system_api_paths = frozenset({MAINTENANCE_PATH})
    app.state.signed_api_paths = frozenset(
        route.path
        for routeur in (peer_router, peer_hosting_router)
        for route in routeur.routes
        if isinstance(route, APIRoute)
    )
    return app
