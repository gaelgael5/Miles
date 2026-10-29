from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

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
    ENVIRONMENT_ATTACHED_EVENT,
    ENVIRONMENT_DESIGNATED_EVENT,
    PAIRING_CONFIRMED_EVENT,
    PAIRING_REVOKED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_EXPIRED_EVENT,
    REQUEST_OBJECT_KIND,
    REQUEST_OPENED_EVENT,
    REQUEST_REJECTED_EVENT,
    SIGNING_KEY_LABEL,
    EnvironmentAlreadyPairedError,
    EnvironmentNotDesignatedError,
    EnvironmentPeer,
    EnvironmentRef,
    EnvironmentUnknownError,
    PairingClockSkewError,
    PairingCode,
    PairingRefusedError,
    PairingRequest,
    PairingSettledError,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.store import (
    db_attach_peer_environment,
    db_delete_expired_requests,
    db_delete_peer,
    db_delete_request,
    db_designate_request_environment,
    db_forget_revocation,
    db_get_peer,
    db_get_peer_base_url_by_environment,
    db_get_request,
    db_get_revocation,
    db_list_peers,
    db_list_requests,
    db_lock_request,
    db_record_revocation,
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

    def _designated_or_refuse(self, demande: PairingRequest) -> EnvironmentRef:
        if demande.environment is None:
            raise EnvironmentNotDesignatedError(
                f"aucun environnement désigné pour {demande.base_url}"
            )
        return demande.environment

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

    async def _refuse_unknown_origin(self, conn: Any, origin: str) -> NoReturn:
        """Refuse une origine sans appariement, en DISANT au journal si elle a été révoquée.

        La réponse servie est la même dans les deux cas, mot pour mot : distinguer
        offrirait un oracle — savoir qu'une origine a déjà été appariée, puis révoquée.
        Seule la ligne de journal change, et c'est tout l'objet du critère 4 : sans elle,
        un exploitant cherche une clé perdue ou une horloge alors qu'un humain a décidé.

        La lecture de la pierre tombale n'a lieu que sur ce chemin de REFUS : un appel
        d'un pair apparié ne la paie jamais.
        """
        if await db_get_revocation(conn, origin) is not None:
            self._refuse("origine_revoquee", origin)
        self._refuse("origine_inconnue", origin)

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appariement_refuse", reason=reason, declared_origin=declared_origin)
        raise PairingRefusedError(reason)
