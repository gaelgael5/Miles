from __future__ import annotations

from datetime import timedelta

import asyncpg
import structlog
from miles_socle.secrets.model import Secret, SecretUndecipherableError
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import validate_declared_name, validate_public_key
from miles_socle.signing.protocol import PeerSpecies

from enrolement.pairing.events import (
    PAIRING_CONFIRMED_EVENT,
    PEER_OBJECT_KIND,
    REQUEST_OBJECT_KIND,
    REQUEST_OPENED_EVENT,
)
from enrolement.pairing.model import (
    ConfirmedPairing,
    EnvironmentAlreadyPairedError,
    PairingClockSkewError,
    PairingRequest,
    PairingSpeciesMismatchError,
    ParametrageAlreadyPairedError,
)
from enrolement.pairing.peer_reads import PairingPeerReads
from enrolement.pairing.store import (
    db_delete_request,
    db_get_request,
    db_lock_request,
    db_upsert_request,
)
from enrolement.pairing.store_peers import (
    db_forget_revocation,
    db_upsert_peer,
)
from enrolement.pairing.totp import (
    ACCEPTED_OFFSETS,
    STEP_S,
    new_totp_secret,
    resolve_code_offset,
)

log = structlog.get_logger(__name__)


class PairingPeerProtocol(PairingPeerReads):
    """Les deux GESTES qu'un pair déclenche : frapper, puis confirmer avec le code.

    Séparé de ce qu'un humain déclenche depuis son écran, parce que les deux n'ont ni la
    même source de confiance ni la même règle d'opacité — ici l'appelant est une machine
    non authentifiée tant que le code n'est pas passé, et rien de ce qu'il reçoit ne doit
    lui apprendre autre chose que « refusé ». Les LECTURES d'un pair — vérifier son appel,
    rendre l'état de sa demande — sont dans `peer_reads.py` : ici on écrit et on conclut.
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
        species: PeerSpecies,
    ) -> PairingRequest:
        """Un demandeur frappe : la demande apparaît, avec un secret tout neuf.

        Le secret NAÎT ici, au moment où le demandeur frappe, et il ne vaut que pour
        cette demande. Frapper à nouveau depuis la même origine renouvelle le secret au
        lieu d'ouvrir une seconde demande : deux demandes pour une même origine, et
        l'humain ne saurait laquelle accepter.

        L'ESPÈCE est enregistrée telle qu'elle est DÉCLARÉE, et elle n'autorise rien par
        elle-même : comme le nom déclaré, elle vient d'un tiers que personne n'a encore
        authentifié. Ce qu'elle fait, c'est permettre à l'humain de lire ce qu'il accepte,
        et c'est son geste — révéler le code — qui autorise.
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
                species,
            )
            await self.module.write_event(
                conn,
                REQUEST_OPENED_EVENT,
                REQUEST_OBJECT_KIND,
                origine,
                {
                    "public_key_fingerprint": fingerprint(public_key),
                    "declared_name": name,
                    # Au journal parce que c'est ce dont découleront les conséquences :
                    # le jour où une stack a reçu ce qu'elle n'aurait pas dû, la première
                    # question est « sous quelle espèce avait-elle frappé ? ».
                    "species": species,
                },
            )
        log.info(
            "demande_d_appariement_ouverte",
            base_url=origine,
            species=species,
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
                # Exigé des environnements, et d'eux seuls : le module de paramétrage ne
                # reçoit pas de devices, et il n'y a rien à lui désigner.
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
                    conn,
                    origine,
                    demande.public_key,
                    maintenant,
                    demande.name,
                    None if environnement is None else environnement.id,
                    # L'adresse de contact vaut l'origine déclarée au premier appariement :
                    # c'est tout ce qu'on sait d'elle, et c'est la stack qui nous a appelés,
                    # jamais l'inverse. Son administrateur la corrigera sur l'écran si un
                    # intermédiaire s'interpose. Au ré-appariement elle n'est pas réécrite.
                    origine,
                    demande.species,
                )
                if pair is None:
                    # Cette origine est appariée sous une AUTRE espèce. Refusé plutôt que
                    # transformé, et la demande N'EST PAS rendue : la transaction entière
                    # est défaite par la levée, donc la suppression ci-dessus aussi — le
                    # code n'est pas brûlé, et un humain peut révoquer puis recommencer.
                    raise PairingSpeciesMismatchError(
                        f"{origine} est appariée sous une autre espèce : révoquer d'abord"
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
                    {
                        "public_key_fingerprint": fingerprint(pair.public_key),
                        # L'espèce est au journal des DEUX faits — la demande et la
                        # conclusion — parce que ce sont deux faits. Celle de la demande
                        # ne suffirait pas : la demande disparaît en se concluant, et
                        # « sous quelle espèce cette stack est-elle appariée ? » doit
                        # rester lisible après.
                        "species": pair.species,
                    },
                )
        except asyncpg.UniqueViolationError as exc:
            # Deux unicités peuvent trancher ici, et elles n'appellent pas le même geste.
            # Dans les deux cas, des confirmations d'origines DIFFÉRENTES ne se croisent
            # pas sur le verrou consultatif, qui porte sur l'origine : la lecture les a
            # vues libres, et c'est la base qui décide. Le refus est le MÊME que celui de
            # la lecture — une course ne doit pas produire un autre message.
            #
            # On lit le NOM de la contrainte plutôt que de supposer laquelle a parlé :
            # supposer ferait dire « choisissez un autre environnement » à qui vient
            # d'apparier un second module de paramétrage, pour lequel il n'y a pas de
            # second choix à faire.
            if exc.constraint_name == "environment_peer_un_seul_parametrage":
                raise ParametrageAlreadyPairedError(
                    "un module de paramétrage est déjà apparié : le révoquer d'abord"
                ) from exc
            raise EnvironmentAlreadyPairedError(
                f"{origine} vise un environnement qu'un autre appariement vient de prendre"
            ) from exc
        log.info(
            "appariement_confirme",
            base_url=origine,
            peer_key_fingerprint=fingerprint(pair.public_key),
            own_key_fingerprint=fingerprint(identite.public_key),
            species=pair.species,
            environment_slug=pair.environment.slug if pair.environment else None,
        )
        return ConfirmedPairing(propre_origine, identite.public_key, identite.algorithm)
