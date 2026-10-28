from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, NoReturn

import asyncpg
import structlog
from miles_socle.events.model import EventAuthor, EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.model import Secret, SecretUndecipherableError
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.calls import (
    CallSignatureError,
    origin_for_log,
    validate_origin,
    verify_call,
)
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.identity_model import ModuleIdentity
from miles_socle.signing.keys import fingerprint, parse_public_key
from miles_socle.signing.peers import validate_declared_name, validate_public_key

from enrolement.pairing.model import (
    PAIRING_CONFIRMED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_EXPIRED_EVENT,
    REQUEST_OBJECT_KIND,
    REQUEST_OPENED_EVENT,
    REQUEST_REJECTED_EVENT,
    SIGNING_KEY_LABEL,
    EnvironmentPeer,
    PairingClockSkewError,
    PairingCode,
    PairingRefusedError,
    PairingRequest,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.store import (
    db_delete_expired_requests,
    db_delete_request,
    db_get_peer,
    db_get_request,
    db_list_peers,
    db_list_requests,
    db_lock_request,
    db_upsert_peer,
    db_upsert_request,
)
from enrolement.pairing.totp import (
    ACCEPTED_OFFSETS,
    STEP_S,
    new_totp_secret,
    resolve_code_offset,
    seconds_remaining,
    totp_code,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ConfirmedPairing:
    """Ce que l'environnement reçoit quand son code est accepté : NOTRE moitié de l'échange.

    C'est le second dépôt de clé. Le premier a eu lieu à la demande, où l'environnement a
    déposé la sienne ; celui-ci rend la nôtre, et à partir de là chacun détient sa clé
    privée et la clé publique de l'autre. Aucune clé privée ne figure ici, dans aucun sens.
    """

    base_url: str
    public_key: str
    algorithm: str


@dataclass(frozen=True)
class PairingService:
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

    async def resolve_identity(self) -> ModuleIdentity:
        return await self.module.resolve_identity()

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
            if not await db_delete_request(conn, origine):  # pragma: no cover - verrou tenu
                # Le code est BRÛLÉ par cette suppression, et c'est elle qui rend l'usage
                # unique : sans ligne retirée, un autre appel est passé avant nous.
                self._refuse("deja_brule", origine)
            pair = await db_upsert_peer(conn, origine, demande.public_key, maintenant, demande.name)
            await self.module.write_event(
                conn,
                PAIRING_CONFIRMED_EVENT,
                PEER_OBJECT_KIND,
                origine,
                {"public_key_fingerprint": fingerprint(pair.public_key)},
            )
        log.info(
            "appariement_confirme",
            base_url=origine,
            peer_key_fingerprint=fingerprint(pair.public_key),
            own_key_fingerprint=fingerprint(identite.public_key),
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
            # Origine valide mais inconnue : ni appariée, ni en attente. C'est le « signé
            # par une clé inconnue » du ticket, et l'origine est au journal.
            self._refuse("origine_inconnue", origine)
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
            self._refuse("origine_inconnue", origine)
        self._verify_or_refuse(cle, signature, origine, method, target, body)
        return None if rangee is None else rangee[0]

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
        _, scelle = rangee
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

    def _own_origin(self) -> str:
        if self.origin is None:
            # Sans adresse publique, l'environnement ne saurait pas quelle origine attendre
            # de nos appels, et les refuserait tous. Mieux vaut refuser l'appariement que
            # le conclure à moitié.
            raise PairingRefusedError("origine_locale_absente")
        return self.origin

    def _verified_origin(self, declared_origin: str | None, signature: str | None) -> str:
        """L'origine déclarée, validée. Les deux refus qui précèdent toute lecture de base."""
        origine_journal = origin_for_log(declared_origin)
        if not signature:
            # Avant l'origine, et l'ordre compte pour le JOURNAL : un appel sans aucune
            # signature n'est pas un appel signé mal présenté, c'est quelqu'un qui frappe
            # une route de pair sans savoir ce qu'elle attend. Journaliser
            # « origine_invalide » enverrait le diagnostic vers une origine mal configurée
            # alors qu'il n'y a rien du tout (mesuré le 28/10/2026 côté environnement).
            self._refuse("absente", origine_journal)
        try:
            return validate_origin(declared_origin or "")
        except CallSignatureError:
            self._refuse("origine_invalide", origine_journal)

    def _verify_or_refuse(
        self,
        public_key: str,
        signature: str | None,
        origin: str,
        method: str,
        target: str,
        body: bytes,
    ) -> None:
        try:
            verify_call(
                parse_public_key(public_key),
                signature,
                origin=origin,
                method=method,
                target=target,
                body=body,
            )
        except CallSignatureError as refus:
            self._refuse(refus.reason, origin)

    async def _purge_expired(self, conn: Any, now: datetime) -> None:
        for base_url in await db_delete_expired_requests(conn, now):
            await self.module.write_event(
                conn, REQUEST_EXPIRED_EVENT, REQUEST_OBJECT_KIND, base_url, {}
            )
            log.info("demande_d_appariement_expiree", base_url=base_url)

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appariement_refuse", reason=reason, declared_origin=declared_origin)
        raise PairingRefusedError(reason)
