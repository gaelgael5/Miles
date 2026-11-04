from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import NoReturn

import asyncpg
import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from miles_socle.events.model import EventTypeCatalog
from miles_socle.pairing.model import EnrolmentPeer, PeerMissingError
from miles_socle.pairing.store import db_get_peer
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.calls import CallSignatureError
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.identity_model import ModuleIdentity
from miles_socle.signing.protocol import PeerSpecies

log = structlog.get_logger(__name__)


class RequesterBase:
    """Les collaborateurs du service, et ce que toutes ses parties emploient.

    `PairingRequesterService` est une seule classe, découpée en plusieurs fichiers parce
    qu'elle dépassait la limite de 300 lignes du dépôt (ticket d'assainissement du
    29/10/2026). Ce n'est PAS une abstraction : rien n'est ajouté à l'exécution, et il
    n'existe toujours qu'une classe concrète par produit.

    Les annotations ci-dessous sont des TYPES, pas des champs : `dataclasses` ne collecte
    que les annotations de la classe qu'il décore, donc les vrais champs restent déclarés
    sur `PairingRequesterService`. Elles existent pour que l'analyse de types sache ce que
    chaque partie touche, et mypy refuse qu'elles divergent de la classe concrète.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    origin: str | None
    http: httpx.AsyncClient
    # Ce que ce module DIT ÊTRE : son nom dans l'échange de vivacité, et l'espèce de
    # demandeur qu'il déclare en frappant chez l'enrôlement. Les deux sont au produit
    # parce qu'ils le nomment ; tout le reste de ce côté du protocole est identique.
    module_name: str
    species: PeerSpecies
    module: ModuleIdentityService

    async def resolve_identity(self) -> ModuleIdentity:
        return await self.module.resolve_identity()

    async def resolve_private_key(self) -> Ed25519PrivateKey:
        return await self.module.resolve_private_key()

    async def resolve_peer(self) -> EnrolmentPeer:
        pair = await db_get_peer(self.pool)
        if pair is None:
            raise PeerMissingError("aucun module d'enrôlement apparié")
        return pair

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appel_signe_refuse", reason=reason, declared_origin=declared_origin)
        raise CallSignatureError(reason)
