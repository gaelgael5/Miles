from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import structlog
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.identity_model import ModuleIdentity

from enrolement.pairing.model import (
    REQUEST_EXPIRED_EVENT,
    REQUEST_OBJECT_KIND,
    EnvironmentNotDesignatedError,
    EnvironmentRef,
    PairingRequest,
)
from enrolement.pairing.store import db_delete_expired_requests

log = structlog.get_logger(__name__)


class PairingBase:
    """Les collaborateurs du service, et les deux gestes que toutes ses parties emploient.

    `PairingService` est une seule classe, découpée en plusieurs fichiers parce qu'elle
    dépassait la limite de 300 lignes du dépôt (ticket d'assainissement du 29/10/2026).
    Ce n'est PAS une abstraction : aucune indirection n'est ajoutée à l'exécution, et il
    n'existe toujours qu'une classe concrète. Chaque partie hérite d'ici, et c'est ici que
    vivent les attributs qu'elles se partagent.

    Les annotations ci-dessous sont des TYPES, pas des champs : `dataclasses` ne collecte
    que les annotations de la classe qu'il décore (mesuré le 29/10/2026), donc les vrais
    champs restent déclarés sur `PairingService`. Elles existent pour que l'analyse de
    types sache ce que chaque partie touche — et mypy refuse qu'elles divergent de celles
    de la classe concrète, ce qui les empêche de se désaccorder en silence.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    origin: str | None
    # Le client des appels SORTANTS. Ce module n'en émettait aucun avant le
    # 29/10/2026 : les environnements l'appelaient, il répondait. La révocation
    # renverse ce sens — il doit prévenir la stack qu'il lui retire l'accès.
    http: httpx.AsyncClient
    request_ttl_s: int
    module: ModuleIdentityService

    async def resolve_identity(self) -> ModuleIdentity:
        return await self.module.resolve_identity()

    def _designated_or_refuse(self, demande: PairingRequest) -> EnvironmentRef:
        if demande.environment is None:
            raise EnvironmentNotDesignatedError(
                f"aucun environnement désigné pour {demande.base_url}"
            )
        return demande.environment

    async def _purge_expired(self, conn: Any, now: datetime) -> None:
        for base_url in await db_delete_expired_requests(conn, now):
            await self.module.write_event(
                conn, REQUEST_EXPIRED_EVENT, REQUEST_OBJECT_KIND, base_url, {}
            )
            log.info("demande_d_appariement_expiree", base_url=base_url)
