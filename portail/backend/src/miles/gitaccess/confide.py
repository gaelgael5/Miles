from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.pairing.events import PEER_OBJECT_KIND
from miles_socle.pairing.model import PeerMissingError
from miles_socle.pairing.peer_calls import peer_detail
from miles_socle.pairing.store import db_get_peer
from miles_socle.secrets.model import SecretError
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.identity_model import OriginMissingError
from miles_socle.signing.peers import IdentityError
from miles_socle.signing.protocol import GIT_CONNECTIONS_PATH

from miles.gitaccess.confide_model import (
    CONFIDED_EVENT,
    CREDENTIAL_RENEWED_EVENT,
    TRANSMISSION_FAILED_EVENT,
    ConfidedSnapshot,
    ConfidingState,
    TransmissionRefusedError,
    TransmissionUnreachableError,
    content_digest,
)
from miles.gitaccess.model import TOKEN_TYPE
from miles.gitaccess.store_confide import (
    db_get_transmission,
    db_next_revision,
    db_record_transmission,
    db_snapshot,
)
from miles.pairing.service import PairingService

log = structlog.get_logger(__name__)

_CONNECTION_KIND = "git_connection"


@dataclass(frozen=True)
class GitConfidingService:
    """Confie au module d'enrôlement les connexions git saisies ici (ticket edcf78bc).

    « On ne va pas s'amuser à rentrer plusieurs fois les infos de connexion git » (Gael,
    27/10/2026) : elles sont saisies UNE fois, ici, et ce service les transmet. Personne
    n'a à les ressaisir ailleurs, et c'est exactement ce que le ticket interdit de demander.

    CE QUI PART EST L'ÉTAT COMPLET, jamais un écart. Une transmission manquée est réparée
    par la suivante, et la suppression d'une connexion n'a pas de message à elle — absente
    de l'état, elle est détruite là-bas. Un écart aurait exigé un ordre, un accusé et une
    file à rejouer, c'est-à-dire un dispositif que ce dépôt n'a pas et dont la première
    panne serait silencieuse.

    IL N'Y A PAS DE RÉESSAI AUTOMATIQUE, et c'est une limite assumée. Une transmission
    échouée est journalisée, l'écran dit « à retransmettre », et un geste la rejoue — la
    retenter en boucle demanderait un outbox, qui est un ticket à lui (7ae31cc0, pas
    encore fait). Ce qui est garanti sans lui : la divergence est VISIBLE, jamais
    silencieuse, et aucun geste d'administration du portail n'échoue parce que l'autre
    module est injoignable.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    pairing: PairingService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_transmit(
        self, author: EventAuthor, trigger: str, renewed: Sequence[str] = ()
    ) -> ConfidingState:
        """Transmet l'état complet au module d'enrôlement apparié.

        Lève `PeerMissingError` quand aucun module d'enrôlement n'est apparié : il n'y a
        personne à qui confier, et ce n'est pas une panne. L'appelant décide — le geste
        manuel le dit à l'écran, les déclencheurs automatiques l'ignorent.
        """
        pair = await self.pairing.resolve_peer()
        instantane = await self._instantane()
        corps = await self._corps(instantane)
        try:
            reponse = await self.pairing.post_signed(pair.contact_url, GIT_CONNECTIONS_PATH, corps)
        except (httpx.HTTPError, OriginMissingError) as panne:
            await self._echec(author, pair.base_url, trigger, type(panne).__name__)
            raise TransmissionUnreachableError(
                "le module d'enrôlement n'a pas répondu : les connexions git restent à transmettre"
            ) from panne
        if reponse.status_code != 200:
            # Son code de refus, jamais son corps : c'est la réponse d'un autre service.
            detail = peer_detail(reponse)
            await self._echec(author, pair.base_url, trigger, detail)
            raise TransmissionRefusedError(detail, reponse.status_code)
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await db_record_transmission(conn, pair.base_url, instantane, maintenant)
            await self._event(
                conn,
                CONFIDED_EVENT,
                ObjectRef(PEER_OBJECT_KIND, pair.base_url),
                author,
                {
                    "revision": instantane.revision,
                    # Les IDENTIFIANTS des connexions, jamais leurs credentials — pas même
                    # tronqués, pas même en cas d'erreur (interdit du ticket).
                    "connections": [c.id for c in instantane.connections],
                    "trigger": trigger,
                },
            )
            for connection_id in renewed:
                # L'event qui MANQUAIT : le socle journalise déjà le remplacement de la
                # valeur d'un secret, mais par son slug. Celui-ci nomme la CONNEXION, qui
                # est ce qu'un humain cherche (critère 11).
                await self._event(
                    conn,
                    CREDENTIAL_RENEWED_EVENT,
                    ObjectRef(_CONNECTION_KIND, connection_id),
                    author,
                    {"revision": instantane.revision, "peer_base_url": pair.base_url},
                )
        log.info(
            "connexions_git_confiees",
            peer_base_url=pair.base_url,
            revision=instantane.revision,
            connections=len(instantane.connections),
            trigger=trigger,
        )
        return ConfidingState(
            pair.base_url,
            instantane.revision,
            maintenant,
            True,
            len(instantane.connections),
        )

    async def resolve_state(self) -> ConfidingState:
        """Ce qui est confié, et si le destinataire détient bien ce que nous avons.

        L'empreinte courante est recalculée à chaque lecture et comparée à celle de la
        dernière transmission : c'est ce qui permet de dire « à retransmettre » au lieu
        d'afficher « confiées » en croyant sa propre intention.
        """
        connexions = await db_snapshot(self.pool)
        empreinte = content_digest(connexions)
        # Lu directement et non par `resolve_peer`, qui lève : « aucun pair » est un état
        # que cet écran doit AFFICHER, pas un refus.
        pair = await db_get_peer(self.pool)
        if pair is None:
            return ConfidingState(None, None, None, False, len(connexions))
        transmise = await db_get_transmission(self.pool)
        if transmise is None:
            return ConfidingState(pair.base_url, None, None, False, len(connexions))
        revision, empreinte_transmise, transmise_le = transmise
        return ConfidingState(
            pair.base_url,
            revision,
            transmise_le,
            # Un avis de RÉVOCATION reçu suffit à ne plus rien garantir : le contrat dit
            # depuis le 30/10/2026 que révoquer un module de paramétrage DÉTRUIT ce qui
            # lui avait été confié, donc la trace que nous gardons ne décrit plus rien.
            #
            # TROUVÉ EN VRAI le 30/10/2026, et par rien d'autre : après une révocation, cet
            # écran affichait « confiées, à jour » à côté de « révoqué », alors que l'autre
            # bout ne détenait plus une seule ligne. L'avis n'est pourtant qu'un INDICE —
            # le contrat l'écrit —, et il peut être démenti par un ré-appariement. Mais
            # l'erreur n'est pas symétrique : dire « à retransmettre » à tort coûte un
            # geste idempotent, croire confié ce qui est détruit coûte un déploiement qui
            # ne lit plus git. On prend donc le risque du premier côté.
            pair.revoked_at is None and empreinte_transmise == empreinte,
            len(connexions),
        )

    async def resolve_transmit_after(
        self, author: EventAuthor, trigger: str, renewed: Sequence[str] = ()
    ) -> None:
        """Transmet APRÈS un geste déjà acquis, sans jamais le faire échouer.

        C'est le chemin de tous les déclencheurs automatiques : déclarer une connexion,
        la modifier, la supprimer, remplacer un PAT. Le geste est commis avant d'arriver
        ici, et il doit le rester — faire dépendre l'administration du portail de la
        disponibilité d'un autre module serait une panne de plus, pas une garantie de
        moins. Ce qui reste d'un échec : une ligne de journal, un event, et un écran qui
        dit « à retransmettre ».
        """
        try:
            await self.resolve_transmit(author, trigger, renewed)
        except PeerMissingError:
            # Aucun module d'enrôlement apparié : il n'y a personne à qui confier, et ce
            # n'est pas une panne. C'est l'état d'un portail qui n'a pas encore frappé.
            return
        except (TransmissionRefusedError, TransmissionUnreachableError):
            # Déjà journalisé par `resolve_transmit`, avec sa cause. Avalé ICI et nulle
            # part ailleurs : le geste manuel, lui, doit voir le refus.
            return
        except (SecretError, IdentityError, asyncpg.PostgresError) as inattendu:
            # Les trois pannes que ce chemin peut rencontrer : un credential devenu
            # illisible, une identité de module inutilisable, une base qui refuse. Elles
            # sont avalées ICI parce que le geste déclencheur est DÉJÀ COMMIS — laisser
            # remonter ferait rendre 500 à une déclaration de connexion réussie, et son
            # auteur la refera en croyant avoir échoué. La cause part au journal, et
            # l'écran montrera la divergence.
            log.error(
                "transmission_des_connexions_git_impossible",
                trigger=trigger,
                reason=type(inattendu).__name__,
            )

    async def _instantane(self) -> ConfidedSnapshot:
        """Lit l'état et alloue sa révision. Les deux ensemble, et dans cet ordre."""
        async with self.pool.acquire() as conn, conn.transaction():
            connexions = await db_snapshot(conn)
            revision = await db_next_revision(conn)
        return ConfidedSnapshot(revision, connexions, content_digest(connexions))

    async def _corps(self, instantane: ConfidedSnapshot) -> bytes:
        """Compose le corps signé. SEUL point où un credential est déballé.

        Les octets sont construits ici et passés tels quels à la signature : les
        réencoder plus loin donnerait une autre suite d'octets, et la signature serait
        refusée à tort. Ce tableau n'est journalisé nulle part.
        """
        connexions = []
        for connexion in instantane.connections:
            credential = await self.secrets.resolve_secret(connexion.token_secret_slug, TOKEN_TYPE)
            connexions.append(
                {
                    "id": connexion.id,
                    "label": connexion.label,
                    "base_url": connexion.base_url,
                    # Déballé au point d'injection, et nulle part avant.
                    "credential": credential.reveal(),
                    "workspaces": [
                        {"id": workspace.id, "repo_url": workspace.repo_url}
                        for workspace in connexion.workspaces
                    ],
                }
            )
        charge = {"revision": instantane.revision, "connections": connexions}
        return json.dumps(charge).encode("utf-8")

    async def _echec(
        self, author: EventAuthor, peer_base_url: str, trigger: str, reason: str
    ) -> None:
        """Journalise l'échec, et l'écrit au journal d'events.

        Un event et pas seulement une ligne de log : « depuis quand le module d'enrôlement
        ne reçoit-il plus ? » est la question du diagnostic, et le journal d'events est ce
        qui se relit par objet et par date. La trace de transmission n'est PAS écrite —
        l'empreinte reste celle de l'ancienne, donc l'écran dit « à retransmettre ».
        """
        log.warning(
            "transmission_des_connexions_git_refusee",
            peer_base_url=peer_base_url,
            trigger=trigger,
            reason=reason,
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await self._event(
                conn,
                TRANSMISSION_FAILED_EVENT,
                ObjectRef(PEER_OBJECT_KIND, peer_base_url),
                author,
                {"trigger": trigger, "reason": reason},
            )

    async def _event(
        self,
        conn: Any,
        event_type: str,
        reference: ObjectRef,
        author: EventAuthor,
        properties: dict[str, Any],
    ) -> None:
        event = NewEvent(event_type, (reference,), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)
