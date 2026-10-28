from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI
from miles_socle.testing.files import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_ENV, admin_env, write_env
from miles_socle.testing.stack import open_socle_stack, utc_now

from environnement.app import build_app
from environnement.config import DEFAULT_MIGRATIONS_DIR
from environnement.event_types import code_event_types
from environnement.identity.service import IdentityService

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

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=BASE_URL)


@asynccontextmanager
async def open_stack(
    dsn: str,
    tmp_path: Path,
    *,
    admin_email: str | None = ADMIN_EMAIL,
    public_url: str = PUBLIC_URL,
    peer_app: FastAPI | None = None,
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
            # Rien n'est engendré ici, et c'est fidèle au démarrage réel : l'identité naît
            # au premier USAGE. Un montage qui la créerait d'avance cacherait justement le
            # cas que la machine de test a révélé.
            yield EnvironnementStack(
                socle.pool, socle.app, socle.client, socle.env_file, socle.http, identity
            )
