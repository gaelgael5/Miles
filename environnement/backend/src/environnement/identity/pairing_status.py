from __future__ import annotations

from dataclasses import replace

import httpx
import structlog
from miles_socle.signing.identity_model import OriginMissingError
from miles_socle.signing.protocol import PAIRING_STATUS_PATH, PING_BODY

from environnement.identity.model import PairingState
from environnement.identity.peer_calls import (
    IdentityPeerCalls,
    demande_disparue,
    peer_detail,
)
from environnement.identity.store import (
    db_clear_peer_revoked,
    db_get_attempt,
    db_get_peer,
    db_mark_peer_revoked,
)

log = structlog.get_logger(__name__)


class IdentityPairingStatus(IdentityPeerCalls):
    """OÙ EN EST l'appariement, et ce qu'on retient de ce que le pair nous pousse.

    Séparé des gestes de l'appariement — frapper, coller le code, annuler — parce que ce
    n'est pas la même chose : là-bas on agit, ici on constate. Et le constat a sa propre
    règle, celle qui tient tout l'écran : ce module détient la moitié que le pair n'a pas
    — l'échéance annoncée —, et c'est elle qui permet de trancher entre une demande
    refusée et une demande expirée. Le pair, lui, ne dit que « en attente » ou « inconnue ».
    """

    async def resolve_pairing_state(self) -> PairingState:
        """L'état complet de l'appariement, celui que l'écran rend lisible.

        Sans demande en cours, il se lit localement. Avec une demande en cours, il faut
        DEMANDER AU PAIR : son refus d'un code et la disparition de la demande rendent le
        même refus opaque — volontairement —, donc rien d'ici ne distinguerait « un humain
        n'a pas encore répondu » de « un humain a dit non ».

        Le pair ne dit que « en attente » ou « inconnue ». C'est NOUS qui tranchons entre
        refusée et expirée, en comparant à l'échéance qu'il nous a annoncée en accusant la
        demande : nous détenons les deux moitiés, lui n'en détient qu'une.
        """
        pair = await db_get_peer(self.pool)
        tentative = await db_get_attempt(self.pool)
        if tentative is None:
            if pair is None:
                return PairingState("non_apparie", None, None)
            # Un appariement enregistré ici ne prouve pas qu'il tient encore EN FACE. On
            # le demande donc au pair à l'affichage, au prix d'un appel borné par
            # `PEER_HTTP_TIMEOUT_S` ; sans cela, l'écran afficherait « apparié » pour
            # toujours à un module que plus personne ne sert.
            #
            # L'avis de révocation reçu NE REMPLACE PAS cet appel, il le DÉSAMBIGUÏSE :
            # l'avis est un indice, l'appel fait foi. Un avis arrivé juste avant un
            # ré-appariement dirait sinon « révoqué » d'un appariement vivant — le
            # contresens que ce ticket corrige, retourné. C'est aussi ce qui permet de
            # l'oublier quand les faits le démentent.
            etat = await self._peer_still_accepts_us(pair)
            if etat == "apparie" and pair.revoked_at is not None:
                await db_clear_peer_revoked(self.pool)
                log.info("avis_de_revocation_dementi", base_url=pair.base_url)
                # La ligne RENDUE porte l'oubli, elle aussi. Sans ce remplacement, la même
                # réponse dirait « apparié » tout en datant une révocation : une charge qui
                # se contredit elle-même fait chercher la panne des deux côtés à la fois.
                pair = replace(pair, revoked_at=None)
            if etat == "refuse_par_le_pair" and pair.revoked_at is not None:
                etat = "revoque"
            return PairingState(etat, None, pair)
        try:
            reponse = await self.post_signed(tentative.base_url, PAIRING_STATUS_PATH, PING_BODY)
        except (httpx.HTTPError, OriginMissingError):
            # Injoignable n'est pas « refusée » : faire recommencer la demande pour une
            # panne de réseau détruirait un appariement en cours d'acceptation.
            log.warning("etat_d_appariement_indisponible", base_url=tentative.base_url)
            return PairingState("pair_injoignable", tentative, pair)
        disparue = demande_disparue(reponse)
        if disparue is None:
            log.warning(
                "etat_d_appariement_indisponible",
                base_url=tentative.base_url,
                status_code=reponse.status_code,
                peer_detail=peer_detail(reponse),
            )
            return PairingState("pair_injoignable", tentative, pair)
        if not disparue:
            return PairingState("en_attente", tentative, pair)
        if tentative.expires_at is None:
            # Sans échéance connue, on ne tranche pas : dire « refusée » quand on ne sait
            # pas enverrait chercher un humain qui n'a rien fait.
            return PairingState("expiree", tentative, pair)
        return PairingState(
            "expiree" if self.now() >= tentative.expires_at else "refusee", tentative, pair
        )

    async def resolve_record_revocation(self) -> None:
        """Retient l'avis de révocation que le pair vient de nous pousser, et VÉRIFIÉ.

        Appelée seulement après `resolve_verify_incoming` : l'avis est signé de la clé du
        pair et déclare son origine, exactement comme l'échange de vivacité. Sans cette
        vérification, n'importe qui ferait croire à une stack qu'elle est révoquée — et
        l'administrateur refrapperait pour rien.

        Rien n'est détruit. L'appariement reste affiché, son empreinte comprise : c'est ce
        qu'on voudra comparer après avoir refrappé.
        """
        if await db_mark_peer_revoked(self.pool, self.now()):
            log.warning("avis_de_revocation_recu")
