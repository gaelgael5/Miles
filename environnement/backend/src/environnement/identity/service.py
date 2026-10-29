from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import httpx
import structlog
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.calls import (
    CallSignatureError,
    origin_for_log,
    validate_origin,
    verify_call,
)
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.keys import parse_public_key
from miles_socle.signing.protocol import PEER_PING_PATH as PEER_PING_PATH

from environnement.identity.assigned_environment import IdentityAssignedEnvironment
from environnement.identity.events import EVENT_TYPES as EVENT_TYPES
from environnement.identity.events import PAIRING_CANCELLED_EVENT as PAIRING_CANCELLED_EVENT
from environnement.identity.events import PAIRING_REQUESTED_EVENT as PAIRING_REQUESTED_EVENT
from environnement.identity.events import (
    PEER_REGISTERED_EVENT as PEER_REGISTERED_EVENT,
)
from environnement.identity.model import (
    SIGNING_KEY_LABEL,
    EnrolmentPeer,
)
from environnement.identity.pairing_flow import IdentityPairingFlow
from environnement.identity.pairing_status import IdentityPairingStatus
from environnement.identity.peer_calls import PEER_HTTP_TIMEOUT_S as PEER_HTTP_TIMEOUT_S
from environnement.identity.peer_calls import PeerPong as PeerPong
from environnement.identity.store import db_get_peer

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IdentityService(IdentityPairingFlow, IdentityPairingStatus, IdentityAssignedEnvironment):
    """L'identité du module et son pair unique : ce que l'environnement ajoute au socle.

    La paire de clés, son secret et son contrôle de cohérence viennent du socle
    (`ModuleIdentityService`) — l'enrôlement emploie exactement le même code, et c'est la
    condition pour que les deux bouts signent et vérifient la même chose. Ce qui est ici
    est ce qui n'appartient qu'à l'environnement : son pair UNIQUE, et les deux sens de
    l'échange avec lui.

    UNE classe, découpée en plusieurs fichiers par héritage — aucune indirection ajoutée à
    l'exécution, et il n'existe toujours qu'une classe concrète. Les parties : les appels
    sortants et la lecture de ce qui revient, les gestes de l'appariement, le constat de
    son état, et l'environnement que l'enrôlement nous a assigné.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    http: httpx.AsyncClient
    # Adresse publique du module, d'où l'origine qu'il déclare en signant. CONFIGURÉE
    # (MILES_PUBLIC_URL) et jamais lue des en-têtes : un `Host` forgé ferait signer pour
    # une origine qui n'est pas la nôtre.
    origin: str | None
    # Composé plutôt que reçu : les appelants (production et harnais de test) construisent
    # déjà ce service avec exactement ce qu'il faut au socle, et leur faire assembler les
    # deux ajouterait un câblage de plus à tenir d'accord — la panne que le socle a
    # justement supprimée.
    module: ModuleIdentityService = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "module",
            ModuleIdentityService(
                self.pool, self.secrets, self.cipher, self.catalog, self.now, SIGNING_KEY_LABEL
            ),
        )

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnrolmentPeer:
        """Vérifie un appel entrant, ou lève. Point d'application du fail closed de ce produit.

        Tous les refus passent par ici et sont journalisés avec l'origine DÉCLARÉE —
        validée avant d'être écrite, parce qu'avant la vérification elle n'est encore
        qu'une entrée anonyme. Ce que l'appelant apprend, lui, se limite à « refusé ».
        """
        origine_journal = origin_for_log(declared_origin)
        pair = await db_get_peer(self.pool)
        if pair is None:
            self._refuse("aucun_pair", origine_journal)
        if not signature:
            # Avant l'origine, et l'ordre compte pour le JOURNAL : un appel sans aucune
            # signature n'est pas un appel signé mal présenté, c'est quelqu'un qui frappe
            # une route de pair sans savoir ce qu'elle attend. Mesuré le 28/10/2026 : en
            # validant l'origine d'abord, un appel entièrement nu était journalisé
            # « origine_invalide », ce qui envoie le diagnostic vers une origine mal
            # configurée alors qu'il n'y a rien du tout.
            self._refuse("absente", origine_journal)
        try:
            origine = validate_origin(declared_origin or "")
        except CallSignatureError:
            self._refuse("origine_invalide", origine_journal)
        if origine != pair.base_url:
            # L'origine déclarée doit être celle du pair apparié. Sans cette comparaison,
            # le champ ne servirait qu'à décorer le journal.
            self._refuse("origine_inattendue", origine_journal)
        try:
            verify_call(
                parse_public_key(pair.public_key),
                signature,
                origin=origine,
                method=method,
                target=target,
                body=body,
            )
        except CallSignatureError as refus:
            self._refuse(refus.reason, origine_journal)
        return pair
