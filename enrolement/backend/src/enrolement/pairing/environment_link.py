from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog
from miles_socle.events.model import EventAuthor
from miles_socle.signing.keys import fingerprint

from enrolement.pairing.base import PairingBase
from enrolement.pairing.model import (
    ENVIRONMENT_ATTACHED_EVENT,
    ENVIRONMENT_DESIGNATED_EVENT,
    PAIRING_REVOKED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_OBJECT_KIND,
    EnvironmentAlreadyPairedError,
    EnvironmentPeer,
    EnvironmentRef,
    EnvironmentUnknownError,
    PairingRequest,
    PairingSettledError,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.store import (
    db_designate_request_environment,
)
from enrolement.pairing.store_peers import (
    db_attach_peer_environment,
    db_delete_peer,
    db_get_peer,
    db_get_peer_base_url_by_environment,
    db_record_revocation,
)

log = structlog.get_logger(__name__)


class PairingEnvironmentLink(PairingBase):
    """Le lien entre un appariement et un environnement du référentiel, dans les deux sens.

    Désigner avant la conclusion, rattacher un appariement hérité, révoquer. Les trois
    sont déclenchés par un humain authentifié devant son écran : leurs refus NOMMENT la
    cause, à l'inverse de ceux des routes de pair, parce que cacher à quelqu'un l'état de
    son propre référentiel ne protège de rien.
    """

    async def resolve_designate_environment(
        self, author: EventAuthor, base_url: str, environment_id: UUID
    ) -> PairingRequest:
        """Désigne l'environnement d'une demande en attente. Libre tant qu'elle l'est.

        Changer d'avis est permis : une désignation qui se verrouillerait au premier clic
        obligerait à refuser la demande pour corriger une erreur de liste déroulante. Ce
        qui ne se change plus, c'est l'environnement d'un appariement CONCLU — le
        déplacer emporterait ses devices sans le dire.
        """
        async with self.pool.acquire() as conn:
            pair = await db_get_peer(conn, base_url)
            if pair is not None and pair.environment is not None:
                # La stack est déjà appariée et rattachée : sa nouvelle demande ne sert
                # qu'à tourner ses clés, et elle a hérité de l'environnement à l'ouverture.
                raise PairingSettledError(
                    f"{base_url} est apparié à {pair.environment.slug} ; révoquer d'abord"
                )
            await self._refuse_if_taken(conn, base_url, environment_id)
            try:
                async with conn.transaction():
                    demande = await db_designate_request_environment(conn, base_url, environment_id)
                    if demande is None or demande.environment is None:
                        raise RequestNotFoundError(f"aucune demande en attente pour {base_url}")
                    await self._write_environment_event(
                        conn,
                        ENVIRONMENT_DESIGNATED_EVENT,
                        REQUEST_OBJECT_KIND,
                        demande.environment,
                        base_url,
                        author,
                    )
            except asyncpg.ForeignKeyViolationError as exc:
                # L'environnement a disparu du référentiel entre l'affichage de la liste
                # et le clic. La clé étrangère tient la garde : une lecture préalable
                # laisserait passer la suppression survenue entre elle et l'écriture.
                raise EnvironmentUnknownError(f"aucun environnement sous {environment_id}") from exc
        log.info(
            "environnement_designe",
            base_url=base_url,
            environment_id=str(environment_id),
            environment_slug=demande.environment.slug,
        )
        return demande

    async def resolve_attach_environment(
        self, author: EventAuthor, base_url: str, environment_id: UUID
    ) -> EnvironmentPeer:
        """Rattache un appariement HÉRITÉ, conclu avant que la désignation n'existe.

        Sans toucher aux clés ni refaire l'appariement : c'est le rattrapage d'un état
        transitoire, pas un nouvel appariement. Un appariement qui porte DÉJÀ un
        environnement n'est pas concerné — l'en changer est une révocation suivie d'un
        réappariement, et ce service ne sait pas le faire autrement.
        """
        async with self.pool.acquire() as conn:
            pair = await db_get_peer(conn, base_url)
            if pair is None:
                raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
            if pair.environment is not None:
                raise PairingSettledError(f"{base_url} est déjà rattaché à {pair.environment.slug}")
            await self._refuse_if_taken(conn, base_url, environment_id)
            try:
                async with conn.transaction():
                    rattache = await db_attach_peer_environment(
                        conn, base_url, environment_id, self.now()
                    )
                    if rattache is None or rattache.environment is None:
                        # La lecture l'a vu libre, un autre onglet l'a rattaché entre-temps.
                        raise PairingSettledError(f"{base_url} vient d'être rattaché ailleurs")
                    await self._write_environment_event(
                        conn,
                        ENVIRONMENT_ATTACHED_EVENT,
                        PEER_OBJECT_KIND,
                        rattache.environment,
                        base_url,
                        author,
                    )
            except asyncpg.ForeignKeyViolationError as exc:
                raise EnvironmentUnknownError(f"aucun environnement sous {environment_id}") from exc
            except asyncpg.UniqueViolationError as exc:
                raise EnvironmentAlreadyPairedError(
                    f"{environment_id} vient d'être pris par un autre appariement"
                ) from exc
        log.info(
            "appariement_rattache",
            base_url=base_url,
            environment_id=str(environment_id),
            environment_slug=rattache.environment.slug,
        )
        return rattache

    async def resolve_revoke_pairing(self, author: EventAuthor, base_url: str) -> EnvironmentPeer:
        """Révoque l'appariement : sa ligne disparaît, et la clé publique du pair avec elle.

        Le geste inverse de l'appariement, et il n'en est pas le symétrique : un
        environnement porte des devices, et ce qu'ils deviennent est une décision, pas un
        effet de bord. Elle est prise (ticket d5ffeb33) : ils sont REMIS EN ATTENTE
        d'affectation, jamais réaffectés vers un repli. « Un device qui ne démarre pas est
        un incident visible ; un device qui démarre sur les mauvaises données est un
        incident invisible. » Rien ici ne doit jamais ressembler à un repli.

        L'environnement, lui, RESTE au référentiel et redevient libre : la révocation
        porte sur l'appariement, pas sur l'environnement. Deux gestes qui n'ont pas les
        mêmes conséquences ne s'enchaînent pas tout seuls.
        """
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            revoque = await db_delete_peer(conn, base_url)
            if revoque is None:
                raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
            empreinte = fingerprint(revoque.public_key)
            # Dans la MÊME transaction que la suppression : une pierre tombale sans
            # suppression dirait révoqué un appariement encore vivant, et une suppression
            # sans pierre tombale ferait journaliser « origine inconnue » le premier appel
            # du pair — soit exactement la fausse piste que le critère 4 interdit.
            await db_record_revocation(conn, base_url, empreinte, maintenant)
            await self.module.write_event(
                conn,
                PAIRING_REVOKED_EVENT,
                PEER_OBJECT_KIND,
                base_url,
                {
                    "public_key_fingerprint": empreinte,
                    # L'environnement quitté est nommé par son identifiant ET par ses deux
                    # noms du moment : c'est sous le nom de l'époque qu'on relira ce
                    # journal. Nul pour un appariement hérité, qui n'en portait aucun.
                    "environment_id": str(revoque.environment.id) if revoque.environment else None,
                    "environment_slug": (revoque.environment.slug if revoque.environment else None),
                    "environment_label": (
                        revoque.environment.label if revoque.environment else None
                    ),
                    # NUL, et jamais 0. Le référentiel des devices n'existe pas encore :
                    # écrire 0 serait indiscernable, dans un an, d'un vrai « aucun device
                    # n'a été libéré » — et c'est précisément cette ligne qu'on viendra
                    # lire le jour où des devices ne démarrent plus.
                    "devices_released": None,
                },
                author=author,
            )
        log.info(
            "appariement_revoque",
            base_url=base_url,
            peer_key_fingerprint=empreinte,
            environment_slug=revoque.environment.slug if revoque.environment else None,
        )
        return revoque

    async def _refuse_if_taken(self, conn: Any, base_url: str, environment_id: UUID) -> None:
        """Refuse un environnement que porte DÉJÀ un autre appariement.

        « Un autre » et non « un » : la même origine qui se redésigne son propre
        environnement n'est pas une collision, c'est un clic sans effet. Cette lecture ne
        tient pas la garde pour de bon — la contrainte d'unicité de la base la tient —,
        elle la nomme pendant que l'humain est encore devant son écran.
        """
        porteur = await db_get_peer_base_url_by_environment(conn, environment_id)
        if porteur is not None and porteur != base_url:
            raise EnvironmentAlreadyPairedError(f"{environment_id} est apparié à {porteur}")

    async def _write_environment_event(
        self,
        conn: Any,
        event_type: str,
        object_kind: str,
        environnement: EnvironmentRef,
        base_url: str,
        author: EventAuthor,
    ) -> None:
        """Le slug et le libellé entrent dans l'event EN PLUS de l'identifiant.

        L'identifiant seul suffirait à retrouver l'environnement aujourd'hui ; il ne
        suffirait pas à relire le journal dans un an, où l'on cherche sous le nom qu'on
        employait à l'époque. Les deux sont renommables, c'est l'identifiant qui fait foi.
        """
        await self.module.write_event(
            conn,
            event_type,
            object_kind,
            base_url,
            {
                "environment_id": str(environnement.id),
                "environment_slug": environnement.slug,
                "environment_label": environnement.label,
            },
            author=author,
        )
