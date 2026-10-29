from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.testing.files import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_ENV, admin_env, write_env
from miles_socle.testing.stack import SocleStack, open_socle_stack, utc_now

from enrolement.app import build_app
from enrolement.config import DEFAULT_MIGRATIONS_DIR
from enrolement.environments.service import EnvironmentService
from enrolement.event_types import code_event_types
from enrolement.pairing.service import PairingService

# Réexportés : les tests d'intégration du produit s'en servent, et ils viennent du socle
# parce que la forme du `.env` et le compte d'amorçage sont imposés par lui, pas choisis ici.
__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BASE_ENV",
    "EnrolementStack",
    "admin_env",
    "open_stack",
    "utc_now",
    "write_env",
]

BASE_URL = "http://enrolement"
PUBLIC_URL = "http://enrolement.test"
ADMIN_EMAIL = "admin@enrolement.invalid"
# Courte, pour que l'expiration soit éprouvée sans attendre : une demande ouverte puis
# relue une seconde plus tard doit avoir disparu. La borne basse de la configuration est
# à 60 s ; ici on passe la valeur directement au service, ce qui est le seul écart avec
# la production et il est volontaire.
REQUEST_TTL_S = 900


@dataclass
class EnrolementStack:
    """Le montage du socle, plus ce que ce produit ajoute : appariement et environnements."""

    pool: asyncpg.Pool
    app: FastAPI
    client: httpx.AsyncClient
    env_file: Path
    http: httpx.AsyncClient
    cipher: SecretCipher
    pairing: PairingService
    environments: EnvironmentService

    def anonymous(self) -> httpx.AsyncClient:
        """Un client SANS session : l'état d'un visiteur, et celui d'un pair qui frappe."""
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=BASE_URL)


@asynccontextmanager
async def open_stack(
    dsn: str,
    tmp_path: Path,
    *,
    admin_email: str | None = ADMIN_EMAIL,
    public_url: str = PUBLIC_URL,
    request_ttl_s: int = REQUEST_TTL_S,
    peer_app: FastAPI | None = None,
) -> AsyncIterator[EnrolementStack]:
    """Monte le produit sur une base réelle, sans passer par uvicorn.

    Les sept services du socle sont câblés par `open_socle_stack`, une fois pour les trois
    produits ; ce qui reste ici est ce que ce produit ajoute. La garde de
    `test_cablage.py` vérifie que rien de ce que pose `app.py` ne manque au montage — et
    elle a mordu le 28/10/2026, à l'ajout du service d'appariement.

    `admin_email=None` monte une installation NEUVE, sans administrateur : c'est l'état
    dans lequel l'écran d'amorçage est ouvert, et le seul où il l'est.

    `peer_app` remplace le réseau par une contrepartie EN PROCESSUS pour le seul appel que
    ce module émette : l'avis de révocation. Sans elle, le client sortant tenterait une
    vraie connexion et l'avis échouerait — ce qui est un cas à éprouver aussi, et c'est
    pourquoi le défaut reste « pas de contrepartie ».
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
        async with httpx.AsyncClient(transport=transport, timeout=5.0) as peer_http:
            yield await _monte(socle, peer_http, public_url, request_ttl_s)


async def _monte(
    socle: SocleStack, peer_http: httpx.AsyncClient, public_url: str, request_ttl_s: int
) -> EnrolementStack:
    """Ce que CE produit ajoute aux sept services que le socle a déjà câblés.

    Sorti de `open_stack` pour que le client des appels sortants soit fermé par son propre
    `async with` : un client laissé ouvert sur une contrepartie en processus survit à la
    campagne et fait traîner des connexions entre les tests.
    """
    pairing = PairingService(
        socle.pool,
        socle.app.state.secrets,
        socle.cipher,
        socle.catalog,
        utc_now,
        public_url,
        # Branché sur la contrepartie en processus quand il y en a une : l'avis de
        # révocation part alors pour de vrai, et se vérifie chez elle.
        peer_http,
        request_ttl_s,
    )
    socle.app.state.pairing = pairing
    environments = EnvironmentService(socle.pool, socle.catalog, utc_now)
    socle.app.state.environments = environments
    # Rien n'est engendré ici, et c'est fidèle au démarrage réel : l'identité naît au
    # premier USAGE. Un montage qui la créerait d'avance cacherait justement le cas que la
    # machine de test a révélé le 28/10/2026 — un démarrage sur base non migrée.
    return EnrolementStack(
        socle.pool,
        socle.app,
        socle.client,
        socle.env_file,
        socle.http,
        socle.cipher,
        pairing,
        environments,
    )
