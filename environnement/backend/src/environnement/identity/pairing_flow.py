from __future__ import annotations

import json
import re

import httpx
import structlog
from miles_socle.events.model import EventAuthor
from miles_socle.signing.identity_model import SINGLETON, OriginMissingError
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import (
    IdentityInputError,
    validate_base_url,
    validate_declared_name,
    validate_public_key,
)
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PING_BODY,
)

from environnement.identity.events import (
    ATTEMPT_OBJECT_KIND,
    PAIRING_CANCELLED_EVENT,
    PAIRING_REQUESTED_EVENT,
    PEER_OBJECT_KIND,
    PEER_REGISTERED_EVENT,
)
from environnement.identity.model import (
    EnrolmentPeer,
    PairingAttempt,
    PairingAttemptMissingError,
    PairingState,
)
from environnement.identity.peer_calls import (
    IdentityPeerCalls,
    demande_disparue,
    peer_detail,
    peer_expires_at,
)
from environnement.identity.store import (
    db_delete_attempt,
    db_get_attempt,
    db_get_peer,
    db_upsert_attempt,
    db_upsert_peer,
)

log = structlog.get_logger(__name__)

# Le code recopié par l'humain : six chiffres, et rien d'autre. Validé AVANT de partir sur
# le réseau — c'est une saisie, et l'envoyer tel quel ferait porter au pair la validation
# d'une entrée qui est la nôtre.
_CODE_RE = re.compile(r"^[0-9]{6}$")


class IdentityPairingFlow(IdentityPeerCalls):
    """Le parcours d'appariement vu de CE module : frapper, coller le code, où on en est.

    Séparé des appels sortants ordinaires parce qu'il a sa propre règle : ce module
    détient la moitié que le pair n'a pas — l'échéance annoncée — et c'est elle qui lui
    permet de trancher entre une demande refusée et une demande expirée. Le pair, lui, ne
    dit que « en attente » ou « inconnue ».
    """

    async def resolve_attempt(self) -> PairingAttempt:
        """La demande d'appariement en cours. Pour que l'écran sache chez qui on a frappé."""
        tentative = await db_get_attempt(self.pool)
        if tentative is None:
            raise PairingAttemptMissingError("aucune demande d'appariement en cours")
        return tentative

    async def resolve_request_pairing(
        self, author: EventAuthor, enrolment_base_url: str, name: str
    ) -> PairingAttempt:
        """Frappe chez le module d'enrôlement et y dépose NOTRE clé publique.

        Premier des deux dépôts. L'appel est signé par notre clé privée, et le pair le
        vérifie contre la clé publique que ce corps porte : cela ne dit pas qui nous
        sommes — un humain le dira avec le code — mais cela prouve que nous détenons bien
        la privée de la publique déposée. Sans quoi n'importe qui déposerait la clé d'un
        autre sous une origine qu'il ne contrôle pas.

        Aucune clé privée ne figure dans ce corps, et il n'en existe aucun champ.
        """
        base_url = validate_base_url(enrolment_base_url)
        # Saisie d'un administrateur : validée ICI, avant de partir. L'envoyer telle quelle
        # ferait porter au pair la validation d'une entrée qui est la nôtre.
        name = validate_declared_name(name)
        identite = await self.resolve_identity()
        corps = json.dumps({"public_key": identite.public_key, "name": name}).encode("utf-8")
        reponse = await self.post_signed(base_url, PAIRING_REQUEST_PATH, corps)
        if reponse.status_code != 202:
            self._refuse_peer(reponse, base_url)
        maintenant = self.now()
        echeance = peer_expires_at(reponse)
        async with self.pool.acquire() as conn, conn.transaction():
            tentative = await db_upsert_attempt(conn, base_url, maintenant, name, echeance)
            await self.module.write_event(
                conn,
                PAIRING_REQUESTED_EVENT,
                ATTEMPT_OBJECT_KIND,
                SINGLETON,
                {
                    "base_url": base_url,
                    "declared_name": name,
                    "public_key_fingerprint": fingerprint(identite.public_key),
                },
                author=author,
            )
        log.info("appariement_demande", base_url=base_url)
        return tentative

    async def resolve_register_peer(
        self,
        author: EventAuthor,
        base_url: str,
        public_key: str,
        declared_name: str | None = None,
    ) -> EnrolmentPeer:
        """Enregistre le module d'enrôlement apparié, ou REMPLACE celui qui existe.

        Jamais un second pair : le modèle n'en admet qu'un, le module d'enrôlement étant
        l'autorité unique sur l'affectation des devices. C'est aussi par ici que passe le
        dépôt de clé à l'issue de l'appariement, et c'est voulu — un seul endroit écrit le
        pair, qu'un humain l'ait saisi ou que le protocole l'ait rapporté.
        """
        base_url, public_key = validate_base_url(base_url), validate_public_key(public_key)
        async with self.pool.acquire() as conn, conn.transaction():
            pair = await db_upsert_peer(conn, base_url, public_key, self.now(), declared_name)
            await self.module.write_event(
                conn,
                PEER_REGISTERED_EVENT,
                PEER_OBJECT_KIND,
                SINGLETON,
                {"base_url": base_url, "public_key_fingerprint": fingerprint(public_key)},
                author=author,
            )
        log.info(
            "pair_enregistre", base_url=base_url, public_key_fingerprint=fingerprint(public_key)
        )
        return pair

    async def resolve_confirm_pairing(self, author: EventAuthor, code: str) -> EnrolmentPeer:
        """Présente le code recopié, et range la clé publique que le pair rend en retour.

        Second dépôt : à l'issue, chacun détient sa clé privée et la clé publique de
        l'autre, et plus aucun appel entre les deux ne demande d'intervention humaine.
        """
        code = _validate_code(code)
        tentative = await self.resolve_attempt()
        corps = json.dumps({"code": code}).encode("utf-8")
        reponse = await self.post_signed(tentative.base_url, PAIRING_CONFIRM_PATH, corps)
        if reponse.status_code != 200:
            self._refuse_peer(reponse, tentative.base_url)
        charge = reponse.json()
        # La clé rendue par le pair est une entrée venue du réseau : validée avant d'être
        # écrite, et avant tout usage comme vérificateur de ses appels.
        public_key = validate_public_key(str(charge["public_key"]))
        base_url = validate_base_url(str(charge["base_url"]))
        pair = await self.resolve_register_peer(author, base_url, public_key, tentative.name)
        async with self.pool.acquire() as conn, conn.transaction():
            # La tentative disparaît APRÈS que le pair est écrit : l'ordre inverse
            # laisserait, sur une panne entre les deux, ni pair ni demande — donc un
            # appariement à refaire depuis le début sans que rien ne le dise.
            await db_delete_attempt(conn)
        log.info(
            "appariement_conclu",
            base_url=base_url,
            peer_key_fingerprint=fingerprint(public_key),
        )
        return pair

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
            # Un appariement enregistré ici ne prouve pas qu'il tient encore EN FACE : le
            # pair a pu le révoquer, et il n'a aucun moyen de nous le dire — il ne nous
            # appelle jamais. On le lui demande donc à l'affichage, au prix d'un appel
            # borné par `PEER_HTTP_TIMEOUT_S`. Sans cela, l'écran afficherait « apparié »
            # pour toujours à un module que plus personne ne sert.
            return PairingState(await self._peer_still_accepts_us(pair), None, pair)
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

    async def resolve_cancel_attempt(self, author: EventAuthor) -> None:
        """Abandonne la demande en cours. Le pair, lui, laissera la sienne expirer."""
        async with self.pool.acquire() as conn, conn.transaction():
            if not await db_delete_attempt(conn):
                raise PairingAttemptMissingError("aucune demande d'appariement en cours")
            await self.module.write_event(
                conn, PAIRING_CANCELLED_EVENT, ATTEMPT_OBJECT_KIND, SINGLETON, {}, author=author
            )
        log.info("appariement_annule")


def _validate_code(code: str) -> str:
    """Six chiffres, débarrassés de TOUT espace — pas seulement de ceux des bords.

    Un code circule par copier-coller : il arrive avec des espaces avant, après, et
    parfois au milieu, parce qu'on l'a lu « 314 159 » sur un écran qui l'aérait. Le
    refuser pour cela revient à refuser le bon code.

    Le nettoyage est ICI et pas seulement dans l'écran. Mesuré sur machine de test le
    28/10/2026 : seul le navigateur nettoyait, et un appel direct à l'API avec « 314 159 »
    rendait 422. Une règle qui ne vit que dans un écran est fausse pour tout autre
    appelant — et pour le prochain écran, qui l'oubliera.
    """
    code = "".join(code.split())
    if not _CODE_RE.match(code):
        raise IdentityInputError("code")
    return code
