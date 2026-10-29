from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.model import EventAuthor, EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.identity import ModuleIdentityService

from enrolement.pairing.environment_link import PairingEnvironmentLink
from enrolement.pairing.model import (
    REQUEST_OBJECT_KIND,
    REQUEST_REJECTED_EVENT,
    SIGNING_KEY_LABEL,
    EnvironmentPeer,
    PairingCode,
    PairingRequest,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.peer_protocol import PairingPeerProtocol
from enrolement.pairing.store import (
    db_delete_request,
    db_get_request,
    db_list_requests,
)
from enrolement.pairing.store_peers import (
    db_get_peer,
    db_list_peers,
)
from enrolement.pairing.totp import seconds_remaining, totp_code

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PairingService(PairingPeerProtocol, PairingEnvironmentLink):
    """Le côté module d'enrôlement du protocole d'appariement (ticket 6a0daab6).

    Trois voies d'entrée, trois sources de confiance différentes, et les confondre serait
    la faute à ne pas commettre :

    - la DEMANDE est signée par la clé que l'environnement dépose dans son corps. Elle ne
      prouve pas qui il est — un humain le dira — mais elle prouve qu'il détient bien la
      clé privée de la clé qu'il dépose. Sans cela, n'importe qui déposerait la clé d'un
      autre ;
    - la CONFIRMATION est signée par la clé déjà déposée dans la demande, et porte le code
      que l'humain a recopié. La signature dit « c'est le même qui revient », le code dit
      « un humain l'a voulu » ; il faut les deux ;
    - les APPELS ORDINAIRES sont signés par la clé d'un environnement déjà apparié.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Adresse publique de CE module, rendue à l'environnement pour qu'il sache quelle
    # origine attendre de nos appels. CONFIGURÉE (MILES_PUBLIC_URL), jamais lue d'un
    # en-tête : un `Host` forgé ferait enregistrer chez le pair une origine qui n'est pas
    # la nôtre, et tous nos appels suivants seraient refusés.
    origin: str | None
    # Durée de vie d'une demande en attente, paramétrable (MILES_PAIRING_REQUEST_TTL_S).
    request_ttl_s: int
    # Composé plutôt que reçu : l'appelant construit déjà ce service avec exactement ce
    # qu'il faut au socle, et lui faire assembler les deux ajouterait un câblage de plus à
    # tenir d'accord — la panne que le socle a justement supprimée.
    module: ModuleIdentityService = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "module",
            ModuleIdentityService(
                self.pool, self.secrets, self.cipher, self.catalog, self.now, SIGNING_KEY_LABEL
            ),
        )

    async def resolve_pending_requests(self) -> list[PairingRequest]:
        """Les demandes en attente, pour l'écran de l'administrateur. Jamais leurs secrets."""
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            return await db_list_requests(conn)

    async def resolve_request_code(self, base_url: str) -> PairingCode:
        """Le code à recopier, recalculé à chaque appel et jamais stocké.

        Il se renouvelle avec la fenêtre : l'écran le redemande, et une capture d'écran
        oubliée cesse de valoir quelque chose. Rien ici ne permet de le conserver.
        """
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            rangee = await db_get_request(conn, base_url)
        if rangee is None:
            raise RequestNotFoundError(f"aucune demande en attente pour {base_url}")
        demande, scelle = rangee
        # Révéler le code EST le geste d'acceptation (ticket ce66f5bb) : la garde est donc
        # ICI, et pas seulement sur le bouton. Un écran qui cacherait le bouton tout en
        # laissant la route répondre livrerait l'appariement à qui connaît l'URL, et
        # l'appariement se conclurait sans que personne ait dit à quel environnement il
        # appartient. C'est le seul endroit où la règle du ticket bf2115cd est tenue.
        self._designated_or_refuse(demande)
        secret = self.cipher.open(base_url, scelle).reveal()
        return PairingCode(base_url, totp_code(secret, maintenant), seconds_remaining(maintenant))

    async def resolve_reject_request(self, author: EventAuthor, base_url: str) -> None:
        """Refus humain : la demande disparaît et son secret avec elle.

        L'environnement l'apprend au premier code qu'il présente — refusé comme tout autre
        appariement impossible —, ce qui vaut mieux que de le laisser en attente indéfinie.
        """
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            if not await db_delete_request(conn, base_url):
                raise RequestNotFoundError(f"aucune demande en attente pour {base_url}")
            await self.module.write_event(
                conn, REQUEST_REJECTED_EVENT, REQUEST_OBJECT_KIND, base_url, {}, author=author
            )
        log.info("demande_d_appariement_refusee", base_url=base_url)

    async def resolve_peers(self) -> list[EnvironmentPeer]:
        return await db_list_peers(self.pool)

    async def resolve_peer(self, base_url: str) -> EnvironmentPeer:
        pair = await db_get_peer(self.pool, base_url)
        if pair is None:
            raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
        return pair
