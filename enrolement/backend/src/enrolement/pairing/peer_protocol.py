from __future__ import annotations

from datetime import timedelta

import asyncpg
import structlog
from miles_socle.secrets.model import Secret, SecretUndecipherableError
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import validate_declared_name, validate_public_key

from enrolement.pairing.model import (
    PAIRING_CONFIRMED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_OBJECT_KIND,
    REQUEST_OPENED_EVENT,
    ConfirmedPairing,
    EnvironmentAlreadyPairedError,
    EnvironmentPeer,
    PairingClockSkewError,
    PairingRequest,
)
from enrolement.pairing.refusals import PairingRefusals
from enrolement.pairing.store import (
    db_delete_request,
    db_get_request,
    db_lock_request,
    db_upsert_request,
)
from enrolement.pairing.store_peers import (
    db_forget_revocation,
    db_get_peer,
    db_upsert_peer,
)
from enrolement.pairing.totp import (
    ACCEPTED_OFFSETS,
    STEP_S,
    new_totp_secret,
    resolve_code_offset,
)

log = structlog.get_logger(__name__)


class PairingPeerProtocol(PairingRefusals):
    """Ce qu'un PAIR déclenche : frapper, confirmer, être vérifié, demander son état.

    Séparé de ce qu'un humain déclenche depuis son écran, parce que les deux n'ont ni la
    même source de confiance ni la même règle d'opacité — ici l'appelant est une machine
    non authentifiée tant que le code n'est pas passé, et rien de ce qu'il reçoit ne doit
    lui apprendre autre chose que « refusé ».
    """

    async def resolve_open_request(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
        public_key: str,
        name: str,
    ) -> PairingRequest:
        """Un environnement frappe : la demande apparaît, avec un secret tout neuf.

        Le secret NAÎT ici, au moment où l'environnement frappe, et il ne vaut que pour
        cette demande. Frapper à nouveau depuis la même origine renouvelle le secret au
        lieu d'ouvrir une seconde demande : deux demandes pour une même origine, et
        l'humain ne saurait laquelle accepter.
        """
        origine = self._verified_origin(declared_origin, signature)
        # Validée avant d'être employée comme clé de vérification. `IdentityInputError`
        # sort en 422 et non en refus opaque : c'est la clé de l'appelant lui-même, mal
        # formée, et lui cacher la cause ne protège personne.
        public_key = validate_public_key(public_key)
        # Nom déclaré par un tiers NON ENCORE AUTHENTIFIÉ : borné et débarrassé de ses
        # caractères de contrôle avant d'entrer en base ou dans un journal. Il n'identifie
        # rien — deux demandes peuvent porter le même, et c'est l'URL qui les distingue.
        name = validate_declared_name(name)
        self._verify_or_refuse(public_key, signature, origine, method, target, body)
        secret = new_totp_secret()
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            demande = await db_upsert_request(
                conn,
                origine,
                public_key,
                # Données associées = l'origine : recopié sur une autre demande, le
                # chiffré ne s'ouvre plus.
                self.cipher.seal(origine, Secret(secret)),
                maintenant,
                maintenant + timedelta(seconds=self.request_ttl_s),
                name,
            )
            await self.module.write_event(
                conn,
                REQUEST_OPENED_EVENT,
                REQUEST_OBJECT_KIND,
                origine,
                {"public_key_fingerprint": fingerprint(public_key), "declared_name": name},
            )
        log.info(
            "demande_d_appariement_ouverte",
            base_url=origine,
            public_key_fingerprint=fingerprint(public_key),
        )
        return demande

    async def resolve_confirm_pairing(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
        code: str,
    ) -> ConfirmedPairing:
        """Le code recopié par l'humain est présenté : l'appariement se conclut, ou est refusé."""
        origine = self._verified_origin(declared_origin, signature)
        # Notre propre adresse publique est exigée AVANT d'écrire quoi que ce soit : la
        # vérifier à la fin conclurait l'appariement en base tout en l'annonçant en échec
        # à l'environnement, qui n'aurait alors pas notre clé — le pire des deux états.
        propre_origine = self._own_origin()
        # AVANT la transaction de confirmation : `resolve_identity` ouvre la sienne, et
        # l'imbriquer prendrait une seconde connexion du pool en tenant la première.
        identite = await self.resolve_identity()
        maintenant = self.now()
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                # Verrou d'abord : deux confirmations simultanées ne doivent pas lire la même
                # demande avant que l'une l'ait brûlée.
                await db_lock_request(conn, origine)
                await self._purge_expired(conn, maintenant)
                rangee = await db_get_request(conn, origine)
                if rangee is None:
                    self._refuse("aucune_demande", origine)
                demande, scelle = rangee
                self._verify_or_refuse(demande.public_key, signature, origine, method, target, body)
                try:
                    secret = self.cipher.open(origine, scelle).reveal()
                except SecretUndecipherableError:
                    # MILES_SECRETS_KEY a changé, ou la ligne a été touchée. La demande ne vaut
                    # plus rien : la brûler évite de laisser un code qu'aucun humain ne pourra
                    # plus faire accepter, et dont le refus resterait inexplicable.
                    await db_delete_request(conn, origine)
                    self._refuse("secret_illisible", origine)
                decalage = resolve_code_offset(secret, code, maintenant)
                if decalage is None:
                    # La demande RESTE en attente : un code faux est une faute de frappe bien
                    # plus souvent qu'une attaque, et détruire la demande punirait la première.
                    self._refuse("code_invalide", origine)
                if decalage not in ACCEPTED_OFFSETS:
                    log.warning(
                        "code_d_appariement_hors_fenetre", base_url=origine, offset_windows=decalage
                    )
                    raise PairingClockSkewError(decalage, STEP_S)
                # Fail closed, et c'est l'interdit central du ticket bf2115cd : aucun
                # appariement neuf ne se conclut sans environnement. Ne devrait jamais
                # mordre ici — le code n'est pas révélable sans désignation — mais la
                # garde est à l'ÉCRITURE, pas seulement à l'écran.
                environnement = self._designated_or_refuse(demande)
                # Pas de lecture de « qui porte déjà cet environnement » avant d'écrire.
                # MESURÉ le 28/10/2026 : elle ne change RIEN. Une violation de contrainte
                # avorte la transaction entière, donc la suppression de la demande est
                # défaite avec le reste — le code n'est pas brûlé, que le refus vienne
                # d'une lecture préalable ou de la base. La garde est la contrainte
                # `environment_peer_environment_unique`, et elle seule.
                if not await db_delete_request(conn, origine):  # pragma: no cover - verrou tenu
                    # Le code est BRÛLÉ par cette suppression, et c'est elle qui rend l'usage
                    # unique : sans ligne retirée, un autre appel est passé avant nous.
                    self._refuse("deja_brule", origine)
                pair = await db_upsert_peer(
                    conn, origine, demande.public_key, maintenant, demande.name, environnement.id
                )
                # Une origine réappariée n'est plus révoquée : sa pierre tombale part avec
                # l'appariement neuf. La laisser ferait dater une révocation ultérieure de
                # la PRÉCÉDENTE, et le diagnostic lirait une date qui ne décrit plus rien.
                # L'historique reste entier dans les events, qui ne s'écrasent pas.
                await db_forget_revocation(conn, origine)
                await self.module.write_event(
                    conn,
                    PAIRING_CONFIRMED_EVENT,
                    PEER_OBJECT_KIND,
                    origine,
                    {"public_key_fingerprint": fingerprint(pair.public_key)},
                )
        except asyncpg.UniqueViolationError as exc:
            # `environment_peer_environment_unique`. Deux confirmations d'origines
            # DIFFÉRENTES visant le même environnement ne se croisent pas sur le verrou
            # consultatif, qui porte sur l'origine : la lecture ci-dessus les a vues libres
            # toutes les deux, et c'est la base qui tranche. Le refus est le MÊME que
            # celui de la lecture — une course ne doit pas produire un autre message.
            raise EnvironmentAlreadyPairedError(
                f"{origine} vise un environnement qu'un autre appariement vient de prendre"
            ) from exc
        log.info(
            "appariement_confirme",
            base_url=origine,
            peer_key_fingerprint=fingerprint(pair.public_key),
            own_key_fingerprint=fingerprint(identite.public_key),
            environment_slug=pair.environment.slug if pair.environment else None,
        )
        return ConfirmedPairing(propre_origine, identite.public_key, identite.algorithm)

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnvironmentPeer:
        """Vérifie l'appel d'un environnement DÉJÀ apparié. Point d'application du fail closed.

        Tous les refus passent par ici et sont journalisés avec l'origine DÉCLARÉE —
        validée avant d'être écrite, parce qu'avant la vérification elle n'est encore
        qu'une entrée anonyme. Ce que l'appelant apprend, lui, se limite à « refusé ».
        """
        origine = self._verified_origin(declared_origin, signature)
        pair = await db_get_peer(self.pool, origine)
        if pair is None:
            await self._refuse_unknown_origin(self.pool, origine)
        self._verify_or_refuse(pair.public_key, signature, origine, method, target, body)
        return pair

    async def resolve_request_state(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> PairingRequest | None:
        """Où en est la demande de l'appelant. Signée : chacun ne lit que la sienne.

        Vérifiée contre la clé que la demande porte — et, si elle a disparu, contre celle
        du pair déjà apparié, parce qu'un environnement qui vient d'être apparié demandera
        encore une fois où il en est avant de rafraîchir son écran. Sans ce second
        recours, sa dernière question serait refusée juste après son succès.

        Rend `None` pour « inconnue », sans dire si elle a été refusée ou si elle a
        expiré : ce module ne garde aucune trace d'une demande disparue. C'est l'appelant
        qui tranche, en comparant à l'échéance qu'il a reçue en frappant.
        """
        origine = self._verified_origin(declared_origin, signature)
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            rangee = await db_get_request(conn, origine)
            pair = None if rangee is not None else await db_get_peer(conn, origine)
        cle = rangee[0].public_key if rangee is not None else (pair.public_key if pair else None)
        if cle is None:
            # Ni demande ni appariement : rien à dire, et surtout pas « inconnue », qui
            # confirmerait à un inconnu que cette origine n'est pas déjà appariée.
            await self._refuse_unknown_origin(self.pool, origine)
        self._verify_or_refuse(cle, signature, origine, method, target, body)
        return None if rangee is None else rangee[0]
