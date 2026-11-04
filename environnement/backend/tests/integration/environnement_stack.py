from __future__ import annotations

from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI
from miles_socle.testing.files import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_ENV, admin_env, write_env
from miles_socle.testing.stack import open_socle_stack, utc_now

from environnement.apikeys.self_key import SelfKeyService
from environnement.apikeys.service import ApiKeysService
from environnement.app import IMPORT_DETAIL_CAP, build_app
from environnement.config import DEFAULT_MIGRATIONS_DIR, Settings
from environnement.event_types import code_event_types
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.service import HostingService
from environnement.identity.service import IdentityService
from environnement.ingestion.deposit_files import FileDeposits
from environnement.ingestion.fileimport import FileImports, ImportLimits
from environnement.ingestion.files import DepositedFiles
from environnement.ingestion.imports import ImportLauncher, pooled_storage_of
from environnement.ingestion.maintenance import ImportsMaintenance
from environnement.ingestion.methods import IngestionMethods
from environnement.ingestion.overview import IngestionOverview
from environnement.ingestion.service import IngestionService
from environnement.ingestion.trial import IngestionTrial
from environnement.storages.service import StoragesService

# Réexportés : les tests d'intégration du produit s'en servent, et ils viennent du socle
# parce que la forme du `.env` et le compte d'amorçage sont imposés par lui, pas choisis ici.
__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BASE_ENV",
    "EnvironnementStack",
    "admin_env",
    "open_stack",
    "utc_now",
    "write_env",
]

BASE_URL = "http://environnement"
PUBLIC_URL = "http://environnement.test"
ADMIN_EMAIL = "admin@environnement.invalid"


@dataclass
class EnvironnementStack:
    """Le montage du socle, plus ce que ce produit ajoute : son service d'identité."""

    pool: asyncpg.Pool
    app: FastAPI
    client: httpx.AsyncClient
    env_file: Path
    http: httpx.AsyncClient
    identity: IdentityService
    hosting: HostingService
    storages: StoragesService
    api_keys: ApiKeysService
    ingestion: IngestionService
    ingestion_overview: IngestionOverview
    ingestion_methods: IngestionMethods
    ingestion_self_key: SelfKeyService
    ingestion_trial: IngestionTrial
    ingestion_files: DepositedFiles
    ingestion_file_deposits: FileDeposits
    ingestion_file_imports: FileImports
    ingestion_imports: ImportLauncher
    ingestion_maintenance: ImportsMaintenance
    tree: HostedTree
    # Les imports LANCÉS mais pas encore déroulés. En production c'est une tâche détachée ;
    # ici on les garde pour que le test décide QUAND l'import tourne — un test qui
    # n'attend pas une tâche de fond ne prouve rien de son résultat (leçon du 24/10/2026
    # sur les tests d'intégration jamais lancés), et c'est aussi ce qui permet de vérifier
    # que le dépôt rend son accusé AVANT que rien ne soit lu.
    lancements: list[Coroutine[Any, Any, Any]] = field(default_factory=list)

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=BASE_URL)

    async def resolve_imports(self) -> None:
        """Déroule les imports lancés, dans l'ordre où ils l'ont été."""
        while self.lancements:
            await self.lancements.pop(0)


@asynccontextmanager
async def open_stack(
    dsn: str,
    tmp_path: Path,
    *,
    admin_email: str | None = ADMIN_EMAIL,
    public_url: str = PUBLIC_URL,
    peer_app: FastAPI | None = None,
    file_max_bytes: int | None = None,
    files_quota_bytes: int | None = None,
    retention_days: int | None = None,
    apply_seconds: float | None = None,
) -> AsyncIterator[EnvironnementStack]:
    """Monte le produit sur une base réelle, sans passer par uvicorn.

    Les sept services du socle sont câblés par `open_socle_stack`, une fois pour les trois
    produits ; ce qui reste ici est ce que ce produit ajoute. La garde de
    `test_cablage_pg.py` vérifie que rien de ce que pose `app.py` ne manque au montage.

    `admin_email=None` monte une installation NEUVE, sans administrateur : c'est l'état
    dans lequel l'écran d'amorçage est ouvert, et le seul où il l'est.

    `peer_app` remplace le réseau par une contrepartie EN PROCESSUS pour les appels
    sortants vers le pair. En production, le service de l'identité partage le client HTTP
    de l'OIDC ; ici il en reçoit un dont le transport mène à la contrepartie, parce que le
    pair est l'AUTRE produit : son côté du protocole s'écrit avec le ticket 6a0daab6, et
    ce qui existe aujourd'hui, c'est le vérificateur du socle — celui-là même qu'il
    emploiera.
    """
    async with open_socle_stack(
        dsn=dsn,
        tmp_path=tmp_path,
        build_app=build_app,
        migrations_dir=DEFAULT_MIGRATIONS_DIR,
        event_types=code_event_types(),
        base_url=BASE_URL,
        public_url=public_url,
        admin_email=admin_email,
    ) as socle:
        transport = None if peer_app is None else httpx.ASGITransport(app=peer_app)
        async with httpx.AsyncClient(transport=transport) as peer_http:
            identity = IdentityService(
                socle.pool,
                socle.app.state.secrets,
                socle.cipher,
                socle.catalog,
                utc_now,
                peer_http,
                public_url,
            )
            socle.app.state.identity = identity
            # L'arbre servi sous `tmp_path` : il part avec le test, comme la base jetable.
            # En production c'est un volume, et git fait foi dans les deux cas.
            tree = HostedTree(tmp_path / "parametrage")
            # Le MÊME arbre pour les deux services, comme dans `app.py` : son verrou
            # sérialise les gestes, et deux objets auraient deux verrous.
            storages = StoragesService(socle.pool, tree, socle.catalog, utc_now)
            socle.app.state.storages = storages
            hosting = HostingService(identity, tree, storages.resolve_materialise)
            socle.app.state.hosting = hosting
            # Le MÊME arbre encore : ce qu'une clé peut ouvrir est ce que la version
            # servie déclare, et cette liste ne doit pas venir d'ailleurs.
            api_keys = ApiKeysService(socle.pool, tree, socle.catalog, utc_now)
            socle.app.state.api_keys = api_keys
            # Le point d'entrée TIENT le vérificateur de clés, comme dans `app.py` :
            # refaire sa vérification ferait diverger le contrôle de la version servie.
            # La borne d'évaluation vient de la CONFIGURATION du produit, comme en
            # production : le harnais appelle ce que la fabrique attend, il ne recompose
            # pas une valeur (leçon du 29/10/2026 sur les harnais trop généreux).
            ingestion = IngestionService(
                socle.pool,
                tree,
                api_keys,
                socle.catalog,
                utc_now,
                _budget_par_defaut(),
            )
            socle.app.state.ingestion = ingestion
            # Le MÊME arbre : ce que l'écran annonce comme points d'entrée doit être
            # ce que le dépôt accepte vraiment.
            apercu = IngestionOverview(socle.pool, tree, api_keys, utc_now)
            socle.app.state.ingestion_overview = apercu
            # Ce que chaque méthode attend, et l'essai depuis l'écran. Le MÊME arbre
            # encore : le schéma que la page montre doit être celui que la validation du
            # dépôt emploiera, sinon l'écran promet une forme que le service refuse.
            methodes = IngestionMethods(tree)
            socle.app.state.ingestion_methods = methodes
            # La clé que le back-office détient pour lui-même. Elle passe par le MÊME
            # vérificateur que n'importe quel partenaire, et sa valeur est rangée dans
            # le magasin de secrets du socle.
            self_key = SelfKeyService(socle.pool, api_keys, socle.app.state.secrets)
            socle.app.state.ingestion_self_key = self_key
            essai = IngestionTrial(socle.pool, self_key, socle.catalog, utc_now)
            socle.app.state.ingestion_trial = essai
            # Le mode gros fichier. Les bornes viennent de la CONFIGURATION du produit,
            # comme en production ; seul le répertoire est sous `tmp_path`, pour partir
            # avec le test. Un test qui veut éprouver un refus de quota monte sa propre
            # borne en argument plutôt que de déformer celle-ci.
            jours = (
                retention_days
                if retention_days is not None
                else _defaut("ingestion_files_retention_days")
            )
            fichiers = DepositedFiles(
                root=tmp_path / "ingestion",
                max_bytes=file_max_bytes or _defaut("ingestion_file_max_bytes"),
                quota_bytes=files_quota_bytes or _defaut("ingestion_files_quota_bytes"),
            )
            socle.app.state.ingestion_files = fichiers
            imports = FileImports(
                socle.pool,
                tree,
                fichiers,
                socle.catalog,
                utc_now,
                ImportLimits(
                    metadata_budget=_defaut("ingestion_metadata_budget"),
                    apply_seconds=apply_seconds or float(_defaut("ingestion_apply_seconds")),
                    detail_cap=IMPORT_DETAIL_CAP,
                    transform_budget=_budget_par_defaut(),
                    retention_days=jours,
                ),
            )
            socle.app.state.ingestion_file_imports = imports
            depots = FileDeposits(socle.pool, tree, api_keys, fichiers, socle.catalog, utc_now)
            socle.app.state.ingestion_file_deposits = depots
            lancements: list[Coroutine[Any, Any, Any]] = []
            lanceur = ImportLauncher(
                drain=imports.resolve_drain,
                storage_of=pooled_storage_of(socle.pool),
                spawn=lancements.append,
            )
            socle.app.state.ingestion_imports = lanceur
            entretien = ImportsMaintenance(
                socle.pool,
                fichiers,
                utc_now,
                jours,
                imports.resolve_drain,
            )
            socle.app.state.ingestion_maintenance = entretien
            # Rien n'est engendré ici, et c'est fidèle au démarrage réel : l'identité naît
            # au premier USAGE. Un montage qui la créerait d'avance cacherait justement le
            # cas que la machine de test a révélé.
            yield EnvironnementStack(
                socle.pool,
                socle.app,
                socle.client,
                socle.env_file,
                socle.http,
                identity,
                hosting,
                storages,
                api_keys,
                ingestion,
                apercu,
                methodes,
                self_key,
                essai,
                fichiers,
                depots,
                imports,
                lanceur,
                entretien,
                tree,
                lancements,
            )


def _defaut(champ: str) -> int:
    """La valeur que la CONFIGURATION du produit pose pour ce champ.

    Lue du champ et non recopiée, pour la même raison que le budget d'évaluation : un
    harnais qui réécrit une valeur de production éprouve autre chose qu'elle.
    """
    return int(Settings.model_fields[champ].default)


def _budget_par_defaut() -> int:
    """La borne d'évaluation telle que la CONFIGURATION du produit la pose.

    Lue du champ et non recopiée : un harnais qui recompose une valeur de production est
    plus généreux ou plus avare qu'elle, et c'est la leçon du 29/10/2026 — on appelle la
    fabrique du produit, on n'en réécrit pas le contenu.
    """
    defaut = Settings.model_fields["transform_budget"].default
    return int(defaut)
