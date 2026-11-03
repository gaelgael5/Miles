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
from miles_socle.events.api_events import router as events_router
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.api_health import router as health_router
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.journal.api_journal import router as journal_router
from miles_socle.log_config import configure_logging
from miles_socle.oidc.api_connectors import router as oidc_connectors_router
from miles_socle.oidc.api_login import router as oidc_login_router
from miles_socle.pairing.api_admin import router as pairing_router
from miles_socle.pairing.api_peer import router as peer_router
from miles_socle.secrets.api_secrets import router as secrets_router
from miles_socle.secrets.api_secrets import types_router as secret_types_router
from miles_socle.secrets.crypto import SecretCipher, parse_secrets_key

from environnement.apikeys.api_apikeys import router as api_keys_router
from environnement.apikeys.service import ApiKeysService
from environnement.config import Settings
from environnement.event_types import code_event_types
from environnement.hosting.api_hosting import router as hosting_router
from environnement.hosting.api_peer_hosting import router as peer_hosting_router
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.service import HostingService
from environnement.identity.api_identity import router as environment_router
from environnement.identity.service import IdentityService
from environnement.ingestion.api_ingest import router as ingest_router
from environnement.ingestion.api_overview import router as ingestion_overview_router
from environnement.ingestion.overview import IngestionOverview
from environnement.ingestion.service import IngestionService
from environnement.storages.api_storages import router as storages_router
from environnement.storages.service import StoragesService

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
        app.state.identity = IdentityService(
            pool,
            app.state.secrets,
            cipher,
            catalog,
            utc_now,
            http,
            settings.public_url,
        )
        # Le service d'hébergement TIENT celui d'identité plutôt que de l'étendre : ce
        # qu'il lui emprunte est l'appel signé et le pair apparié, pas son métier.
        tree = HostedTree(settings.hosting_tree_dir)
        # Le MÊME arbre pour les deux services, et pas un second ouvert sur le même
        # chemin : son verrou sérialise les gestes, et deux objets auraient deux verrous
        # — donc une lecture de déclaration pendant qu'un bundle se pose.
        app.state.storages = StoragesService(pool, tree, catalog, utc_now)
        # Les clés d'ingestion lisent le MÊME arbre : ce qu'une clé peut ouvrir est ce
        # que la version servie déclare, et cette liste ne doit pas venir d'ailleurs.
        app.state.api_keys = ApiKeysService(pool, tree, catalog, utc_now)
        # Le point d'entrée d'ingestion TIENT le vérificateur de clés plutôt que de
        # refaire son travail : la vérification compare l'octroi ET la version servie,
        # et la dupliquer ferait diverger le second contrôle.
        app.state.ingestion = IngestionService(pool, tree, app.state.api_keys, catalog, utc_now)
        # L'écran de l'ingestion : lecture seule, et le MÊME arbre encore — ce qu'il
        # annonce comme points d'entrée doit être ce que le dépôt accepte vraiment.
        app.state.ingestion_overview = IngestionOverview(pool, tree, app.state.api_keys, utc_now)
        # La pose d'une version matérialise les tables de ses storages. Un crochet, et
        # non un appel direct : l'hébergement sait poser un arbre et dire qu'il vient
        # de le poser, il n'a rien à savoir des storages.
        app.state.hosting = HostingService(
            app.state.identity, tree, app.state.storages.resolve_materialise
        )
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
    # L'entretien des journaux partitionnés, appelé par un déclencheur d'HÔTE (décision du
    # 03/11/2026) : ni cookie ni personne derrière. Il vit dans /api et le portillon le
    # laisse passer par `system_api_paths` — déclaré ci-dessous DEPUIS le routeur qui le
    # porte, pour que le chemin et sa vérification ne puissent pas se séparer.
    app.include_router(journal_router)
    # La consultation du journal d'events (story 50bfcba0). DANS /api et hors de toute
    # liste de passage : le portillon exige donc une session, ce qui est le but — le
    # journal dit qui a fait quoi.
    app.include_router(events_router)
    app.include_router(auth_router)
    app.include_router(secrets_router)
    app.include_router(secret_types_router)
    app.include_router(cultures_router)
    app.include_router(login_cultures_router)
    app.include_router(oidc_connectors_router)
    app.include_router(oidc_login_router)
    app.include_router(preferences_router)
    # L'appariement vu du demandeur vient du socle ; ce produit n'ajoute que la lecture de
    # l'environnement que l'enrôlement lui assigne. Les deux routeurs portent le même
    # préfixe, et c'est voulu : il nomme ce que les routes servent, pas qui les porte.
    app.include_router(pairing_router)
    app.include_router(environment_router)
    app.include_router(hosting_router)
    app.include_router(storages_router)
    app.include_router(api_keys_router)
    app.include_router(ingestion_overview_router)
    # HORS de `/api`, donc hors du portillon de sessions : la seule surface de ce
    # module ouverte à un système TIERS, et elle s'authentifie elle-même par clé
    # d'API avant de lire quoi que ce soit. `test_app.py` garde cette liste : toute
    # autre route posée hors de `/api` fera rougir, et c'est exactement ce qu'on veut
    # — une route hors du portillon est une décision, jamais un oubli.
    app.include_router(ingest_router)
    # Routes authentifiées par SIGNATURE, et le portillon ne les laisse passer que parce
    # qu'elles le sont. La liste est DÉRIVÉE du routeur qui les porte, jamais retapée :
    # un chemin ouvert à côté de sa vérification serait ouvert à tous, et c'est
    # exactement l'erreur que cette dérivation rend inexprimable.
    app.include_router(peer_router)
    # L'ordre de version vient de l'enrôlement, authentifié par signature lui aussi, et
    # son routeur est à part : celui du socle sert l'appariement — le même pour les deux
    # demandeurs — tandis que l'hébergement n'est l'affaire que de cette espèce-ci. Les
    # DEUX entrent dans la liste blanche, par dérivation de ce que les routeurs portent :
    # un chemin ouvert à côté de sa vérification serait ouvert à tous.
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
