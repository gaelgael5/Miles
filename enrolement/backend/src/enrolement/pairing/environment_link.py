from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog
from miles_socle.events.model import EventAuthor

from enrolement.pairing.base import PairingBase
from enrolement.pairing.events import (
    ENVIRONMENT_ATTACHED_EVENT,
    ENVIRONMENT_DESIGNATED_EVENT,
    ENVIRONMENT_MOVED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_OBJECT_KIND,
)
from enrolement.pairing.model import (
    EnvironmentAlreadyPairedError,
    EnvironmentNotApplicableError,
    EnvironmentPeer,
    EnvironmentRef,
    EnvironmentUnknownError,
    PairingCarriesDevicesError,
    PairingChangedElsewhereError,
    PairingRequest,
    PairingSettledError,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.store import (
    db_designate_request_environment,
    db_get_request,
)
from enrolement.pairing.store_peers import (
    db_count_peer_devices,
    db_get_peer,
    db_get_peer_base_url_by_environment,
    db_set_peer_environment,
)

log = structlog.get_logger(__name__)


class PairingEnvironmentLink(PairingBase):
    """Le lien entre un appariement et un environnement du référentiel, dans les deux sens.

    Désigner avant la conclusion, poser l'environnement d'un appariement conclu — qu'il
    n'en ait jamais porté ou qu'il en change —, révoquer. Tous sont déclenchés par un
    humain authentifié devant son écran : leurs refus NOMMENT la cause, à l'inverse de ceux
    des routes de pair, parce que cacher à quelqu'un l'état de son propre référentiel ne
    protège de rien.
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
            await self._refuse_if_not_environnement(conn, base_url)
            pair = await db_get_peer(conn, base_url)
            if pair is not None and pair.environment is not None:
                # La stack est déjà appariée et rattachée : sa nouvelle demande ne sert
                # qu'à tourner ses clés, et elle a hérité de l'environnement à l'ouverture.
                # Le changement se fait sur l'APPARIEMENT, pas sur la demande — la
                # conclusion réécrirait l'héritage et le choix fait ici serait perdu.
                raise PairingSettledError(
                    f"{base_url} est apparié à {pair.environment.slug} :"
                    " changer l'environnement de l'appariement lui-même"
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

    async def resolve_set_peer_environment(
        self, author: EventAuthor, base_url: str, environment_id: UUID
    ) -> EnvironmentPeer:
        """Pose l'environnement d'un appariement CONCLU : rattachement ou déplacement.

        Un seul geste pour l'humain — « cet appariement appartient à cet environnement » —,
        et deux faits distincts selon ce qu'il y avait avant : RATTACHER un appariement
        hérité, conclu avant que la désignation n'existe, ou le DÉPLACER d'un environnement
        vers un autre. Deux events, parce que c'est sous l'un ou l'autre nom qu'on relira
        le journal, et jamais sous « le champ a changé ».

        Dans les deux cas, sans toucher aux clés ni refaire l'appariement. Le déplacement
        est ouvert tant que l'appariement ne porte AUCUN device (arbitrage de Gael du
        29/10/2026, ticket 8803f092, qui renverse la règle « révoquer puis réapparier » du
        ticket bf2115cd) : sans device il n'emporte rien et c'est une correction de saisie ;
        avec des devices il emporte leur destination, et déplacer des devices est un geste à
        part, qui se voit, se compte et se confirme pour lui-même.
        """
        async with self.pool.acquire() as conn:
            pair = await db_get_peer(conn, base_url)
            if pair is None:
                raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
            if pair.species != "environnement":
                # Le module de paramétrage ne reçoit pas de devices : lui rattacher un
                # environnement n'a pas de sens, et le laisser possible CONSOMMERAIT —
                # par l'unicité de `environment_id` — un environnement qu'aucune stack
                # ne servirait jamais. Refusé en le nommant plutôt que par la contrainte
                # `environment_peer_environnement_seul_rattache`, qui n'explique rien.
                raise EnvironmentNotApplicableError(
                    f"{base_url} est apparié comme module de paramétrage :"
                    " il ne reçoit pas de devices"
                )
            quitte = pair.environment
            if quitte is not None and quitte.id == environment_id:
                # Reposer le même environnement ne change rien et ne casse pas : c'est un
                # clic sans effet, pas un conflit. Sorti AVANT la garde des devices, sinon
                # un appariement peuplé ne pourrait plus confirmer son propre état.
                return pair
            if quitte is not None:
                await self._refuse_if_devices(conn, base_url)
            await self._refuse_if_taken(conn, base_url, environment_id)
            try:
                async with conn.transaction():
                    pose = await db_set_peer_environment(
                        conn,
                        base_url,
                        environment_id,
                        self.now(),
                        None if quitte is None else quitte.id,
                    )
                    if pose is None or pose.environment is None:
                        # La lecture l'a vu dans un état, un autre onglet l'a changé
                        # entre-temps : c'est la course que la clause `WHERE` ferme.
                        raise PairingChangedElsewhereError(
                            f"l'environnement de {base_url} vient d'être changé ailleurs"
                        )
                    await self._write_environment_event(
                        conn,
                        ENVIRONMENT_ATTACHED_EVENT if quitte is None else ENVIRONMENT_MOVED_EVENT,
                        PEER_OBJECT_KIND,
                        pose.environment,
                        base_url,
                        author,
                        quitte=quitte,
                    )
            except asyncpg.ForeignKeyViolationError as exc:
                raise EnvironmentUnknownError(f"aucun environnement sous {environment_id}") from exc
            except asyncpg.UniqueViolationError as exc:
                # Le refus vient de LA CONTRAINTE, pas de la lecture ci-dessus : celle-ci
                # nomme la cause pendant que l'humain est devant son écran, mais elle ne
                # voit pas l'appariement qui prend l'environnement entre les deux.
                raise EnvironmentAlreadyPairedError(
                    f"{environment_id} vient d'être pris par un autre appariement"
                ) from exc
        log.info(
            "appariement_rattache" if quitte is None else "appariement_deplace",
            base_url=base_url,
            environment_id=str(environment_id),
            environment_slug=pose.environment.slug,
            # Nul au rattachement : il n'y avait rien à quitter.
            previous_environment_slug=None if quitte is None else quitte.slug,
        )
        return pose

    async def _refuse_if_not_environnement(self, conn: Any, base_url: str) -> None:
        """Refuse de désigner un environnement à une demande qui n'en est pas une.

        Lue sur la DEMANDE et non sur l'appariement : c'est elle qui porte l'espèce avant
        la conclusion, et c'est elle qui serait écrite. Une demande absente n'est pas
        refusée ici — le refus « aucune demande en attente » est celui de l'écriture, et
        l'anticiper ferait deux messages pour un seul état.
        """
        rangee = await db_get_request(conn, base_url)
        if rangee is not None and rangee[0].species != "environnement":
            raise EnvironmentNotApplicableError(
                f"{base_url} demande à s'apparier comme module de paramétrage :"
                " il ne reçoit pas de devices"
            )

    async def _refuse_if_devices(self, conn: Any, base_url: str) -> None:
        """LE SEUL endroit où le compte de devices d'un appariement décide de quelque chose.

        Volontairement une méthode à elle, appelée d'un seul point : c'est ici qu'on
        branchera le parc, et une garde recopiée là où elle sert se rebranche une fois de
        moins qu'elle n'est écrite. Elle ne mord sur rien aujourd'hui — le référentiel des
        devices n'existe pas, `db_count_peer_devices` rend zéro — et c'est dit en livrant ;
        un test lui injecte un compte non nul pour éprouver qu'elle mord bien.
        """
        devices = await db_count_peer_devices(conn, base_url)
        if devices > 0:
            raise PairingCarriesDevicesError(base_url, devices)

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
        quitte: EnvironmentRef | None = None,
    ) -> None:
        """Le slug et le libellé entrent dans l'event EN PLUS de l'identifiant.

        L'identifiant seul suffirait à retrouver l'environnement aujourd'hui ; il ne
        suffirait pas à relire le journal dans un an, où l'on cherche sous le nom qu'on
        employait à l'époque. Les deux sont renommables, c'est l'identifiant qui fait foi.

        `quitte` porte l'environnement QUITTÉ lors d'un déplacement — les trois mêmes
        champs, préfixés. Les champs sont ABSENTS et non nuls quand il n'y a rien à
        quitter : une désignation qui porterait `previous_environment_id: null` ferait
        chercher un déplacement qui n'a pas eu lieu.
        """
        charge: dict[str, str] = {
            "environment_id": str(environnement.id),
            "environment_slug": environnement.slug,
            "environment_label": environnement.label,
        }
        if quitte is not None:
            charge["previous_environment_id"] = str(quitte.id)
            charge["previous_environment_slug"] = quitte.slug
            charge["previous_environment_label"] = quitte.label
        await self.module.write_event(
            conn,
            event_type,
            object_kind,
            base_url,
            charge,
            author=author,
        )
