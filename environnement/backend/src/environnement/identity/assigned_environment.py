from __future__ import annotations

import httpx
import structlog
from miles_socle.pairing.peer_calls import RequesterPeerCalls, peer_detail
from miles_socle.signing.identity_model import OriginMissingError
from miles_socle.signing.protocol import (
    ENVIRONMENT_BODY,
    PEER_ENVIRONMENT_PATH,
    PeerEnvironmentOut,
)
from pydantic import ValidationError

from environnement.identity.model import AssignedEnvironmentView
from environnement.identity.store import (
    db_clear_assigned_environment,
    db_get_assigned_environment,
    db_save_assigned_environment,
)

log = structlog.get_logger(__name__)


class IdentityAssignedEnvironment(RequesterPeerCalls):
    """À quel environnement du référentiel l'enrôlement nous a rattachés.

    Ce module ne CHOISIT pas son environnement et ne doit jamais pouvoir le faire : la
    décision est prise par un humain chez l'enrôlement, qui est l'autorité unique sur
    l'affectation des devices. Ici on la lit, on la mémorise, et on l'affiche — rien de
    plus. Il n'existe donc aucune écriture de ce champ qui ne vienne d'une réponse du pair.

    Dans son propre fichier parce que sa règle n'est celle d'aucune autre partie : la
    valeur vient d'un autre service, donc l'absence de réponse n'est pas une absence de
    valeur, et un repli daté vaut mieux qu'une page vide.
    """

    async def resolve_assigned_environment(self) -> AssignedEnvironmentView:
        """Demande au pair, mémorise ce qu'il dit, et affiche. À défaut, le dernier connu.

        Lève `PeerMissingError` quand aucun enrôlement n'est apparié : il n'y a alors
        personne à qui demander, et aucune valeur mémorisée ne pourrait venir de nulle part.

        L'appel est borné par `PEER_HTTP_TIMEOUT_S`, comme les autres : un pair lent ne
        doit pas retenir l'affichage d'une page d'administration.
        """
        pair = await self.resolve_peer()
        try:
            reponse = await self.post_signed(
                # L'adresse de CONTACT, pas l'identité : le pair peut se nommer ailleurs
                # qu'où on le joint, et composer son identité ne marche plus dès qu'un
                # intermédiaire s'interpose.
                pair.contact_url,
                PEER_ENVIRONMENT_PATH,
                ENVIRONMENT_BODY,
            )
        except (httpx.HTTPError, OriginMissingError) as panne:
            # Les DEUX adresses au journal : « où croyait-on l'appeler ? » est la première
            # question d'un pair qu'on ne joint plus, et l'identité seule n'y répond pas.
            log.warning(
                "environnement_assigne_injoignable",
                base_url=pair.base_url,
                contact_url=pair.contact_url,
                reason=type(panne).__name__,
            )
            return await self._dernier_connu()
        if reponse.status_code != 200:
            # Un refus n'est PAS une absence d'environnement. Révocation chez le pair,
            # clés qui ne se correspondent plus, portillon d'authentification qui parle
            # avant lui : rien de tout cela ne dit que nous ne sommes rattachés à rien, et
            # le lire ainsi effacerait une valeur mémorisée parfaitement vraie. L'état de
            # l'appariement, lui, est l'affaire de l'écran d'appariement.
            log.warning(
                "environnement_assigne_refuse",
                base_url=pair.base_url,
                status_code=reponse.status_code,
                peer_detail=peer_detail(reponse),
            )
            return await self._dernier_connu()
        try:
            charge = PeerEnvironmentOut.model_validate_json(reponse.content)
        except ValidationError:
            # La forme est bornée par le CONTRAT, partagé par les deux bouts : ce qui
            # n'est pas à cette forme vient d'autre chose que de la route qu'on croit
            # avoir appelée. Le relire quand même écrirait dans notre base ce qu'un
            # inconnu a renvoyé.
            log.warning(
                "environnement_assigne_illisible",
                base_url=pair.base_url,
                contact_url=pair.contact_url,
            )
            return await self._dernier_connu()
        if charge.environment is None:
            # Réponse FRAÎCHE qui dit « rien » : la valeur mémorisée ne lui survit pas.
            await db_clear_assigned_environment(self.pool)
            log.info("aucun_environnement_assigne", base_url=pair.base_url)
            return AssignedEnvironmentView(None, True)
        return AssignedEnvironmentView(
            # Relu après écriture : c'est la valeur rangée que l'écran affichera, pas
            # celle qu'on croyait ranger.
            await db_save_assigned_environment(
                self.pool, charge.environment.slug, charge.environment.label, self.now()
            ),
            True,
        )

    async def _dernier_connu(self) -> AssignedEnvironmentView:
        """La dernière valeur mémorisée, marquée NON FRAÎCHE. Nulle si on n'a jamais su.

        `fresh=False` est porté explicitement et ne se déduit pas de l'absence de valeur :
        « injoignable et jamais rien su » et « le pair dit qu'il n'y a rien » donnent tous
        deux une vue sans environnement, et les confondre annoncerait « aucun
        environnement rattaché » à un administrateur dont le réseau est coupé.
        """
        return AssignedEnvironmentView(await db_get_assigned_environment(self.pool), False)
