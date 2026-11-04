from __future__ import annotations

import json
import re

import structlog

from miles_socle.events.model import EventAuthor
from miles_socle.pairing.events import (
    ATTEMPT_OBJECT_KIND,
    PAIRING_CANCELLED_EVENT,
    PAIRING_REQUESTED_EVENT,
    PEER_OBJECT_KIND,
    PEER_REGISTERED_EVENT,
)
from miles_socle.pairing.model import (
    EnrolmentPeer,
    PairingAttempt,
    PairingAttemptMissingError,
)
from miles_socle.pairing.peer_calls import RequesterPeerCalls, peer_expires_at
from miles_socle.pairing.store import (
    db_delete_attempt,
    db_get_attempt,
    db_upsert_attempt,
    db_upsert_peer,
)
from miles_socle.signing.identity_model import SINGLETON
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import (
    IdentityInputError,
    validate_base_url,
    validate_declared_name,
    validate_public_key,
)
from miles_socle.signing.protocol import PAIRING_CONFIRM_PATH, PAIRING_REQUEST_PATH

log = structlog.get_logger(__name__)

# Le code recopié par l'humain : six chiffres, et rien d'autre. Validé AVANT de partir sur
# le réseau — c'est une saisie, et l'envoyer tel quel ferait porter au pair la validation
# d'une entrée qui est la nôtre.
_CODE_RE = re.compile(r"^[0-9]{6}$")


class RequesterPairingFlow(RequesterPeerCalls):
    """Les GESTES de l'appariement vus de ce module : frapper, coller le code, annuler.

    Séparé des appels sortants ordinaires parce qu'ici chaque geste écrit — une tentative,
    un pair, un event — et qu'un appel sortant qui échoue à mi-chemin doit laisser la base
    dans un état qu'un humain puisse reprendre. Le CONSTAT de l'état, lui, est dans
    `status.py` : on agit d'un côté, on observe de l'autre.
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

        L'ESPÈCE part avec, et elle ne vient pas de la saisie : elle est ce que ce module
        EST, pas ce qu'un administrateur en dit. Elle permet à l'humain de l'autre bout de
        lire ce qu'il accepte — un environnement et un module de paramétrage n'ont pas les
        mêmes conséquences — et elle n'autorise rien par elle-même.

        Aucune clé privée ne figure dans ce corps, et il n'en existe aucun champ.
        """
        base_url = validate_base_url(enrolment_base_url)
        # Saisie d'un administrateur : validée ICI, avant de partir. L'envoyer telle quelle
        # ferait porter au pair la validation d'une entrée qui est la nôtre.
        name = validate_declared_name(name)
        identite = await self.resolve_identity()
        corps = json.dumps(
            {"public_key": identite.public_key, "name": name, "species": self.species}
        ).encode("utf-8")
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
                    # Au journal parce que c'est ce qu'on a DÉCLARÉ être : le jour où un
                    # appariement n'a pas les droits attendus, la première question est
                    # « sous quelle espèce avions-nous frappé ? ».
                    "species": self.species,
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
        contact_url: str,
        declared_name: str | None = None,
    ) -> EnrolmentPeer:
        """Enregistre le module d'enrôlement apparié, ou REMPLACE celui qui existe.

        Jamais un second pair : le modèle n'en admet qu'un, le module d'enrôlement étant
        l'autorité unique sur l'affectation des devices. C'est aussi par ici que passe le
        dépôt de clé à l'issue de l'appariement, et c'est voulu — un seul endroit écrit le
        pair, qu'un humain l'ait saisi ou que le protocole l'ait rapporté.

        `base_url` et `contact_url` sont deux choses, et les confondre est l'erreur que ce
        ticket corrige : la première est l'IDENTITÉ du pair — ce qu'il déclare être, et la
        seule chose contre quoi on vérifie l'origine d'un appel entrant —, la seconde est
        l'ADRESSE où on le joint. `contact_url` est EXIGÉE des deux appelants plutôt que
        déduite : un défaut calculé ici ferait composer l'identité par mégarde le jour où
        un appelant l'oublierait, et le symptôme — des appels qui n'arrivent pas —
        apparaîtrait loin de sa cause.
        """
        base_url, public_key = validate_base_url(base_url), validate_public_key(public_key)
        # Validée comme l'identité : elle vient d'une saisie, et sert ensuite à composer
        # une URL. Une entrée qui devient une adresse se valide avant tout usage.
        contact_url = validate_base_url(contact_url)
        async with self.pool.acquire() as conn, conn.transaction():
            pair = await db_upsert_peer(
                conn, base_url, public_key, self.now(), declared_name, contact_url
            )
            await self.module.write_event(
                conn,
                PEER_REGISTERED_EVENT,
                PEER_OBJECT_KIND,
                SINGLETON,
                {
                    "base_url": base_url,
                    "public_key_fingerprint": fingerprint(public_key),
                    # Au journal parce qu'une stack qu'on ne joint plus se diagnostique
                    # d'abord par « où croyait-on l'appeler ? ».
                    "contact_url": contact_url,
                },
                author=author,
            )
        log.info(
            "pair_enregistre",
            base_url=base_url,
            contact_url=contact_url,
            public_key_fingerprint=fingerprint(public_key),
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
        # L'adresse de contact est celle que l'administrateur a TAPÉE et qu'on vient de
        # composer avec succès ; l'identité est celle que le pair déclare être la sienne.
        # Jusqu'ici la première était jetée, et c'est tout le défaut : dès qu'un
        # intermédiaire s'interpose, on recomposait une adresse qui n'aboutit plus.
        pair = await self.resolve_register_peer(
            author, base_url, public_key, tentative.base_url, tentative.name
        )
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
