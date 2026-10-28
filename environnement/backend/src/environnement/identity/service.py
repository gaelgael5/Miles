from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

import asyncpg
import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import (
    LOCAL_DIRECTORY,
    EventAuthor,
    EventTypeCatalog,
    NewEvent,
    ObjectRef,
)
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.model import Consumer, Secret
from miles_socle.secrets.service import SecretsService
from miles_socle.secrets.store import db_declare_usage, db_insert_secret
from miles_socle.signing.calls import (
    ORIGIN_HEADER,
    SIGNATURE_HEADER,
    CallSignatureError,
    origin_for_log,
    sign_call,
    validate_origin,
    verify_call,
)
from miles_socle.signing.keys import (
    encode_public_key,
    fingerprint,
    generate_keypair,
    load_private_key,
    parse_public_key,
)

from environnement.identity.model import (
    SIGNING_KEY_CONSUMER_KIND,
    SIGNING_KEY_LABEL,
    SIGNING_KEY_SLUG,
    SIGNING_KEY_TYPE,
    SINGLETON,
    EnrolmentPeer,
    IdentityError,
    IdentityInconsistentError,
    IdentityMissingError,
    ModuleIdentity,
    OriginMissingError,
    PeerMissingError,
    PeerRefusedError,
    PeerUnexpectedResponseError,
    validate_base_url,
    validate_public_key,
)
from environnement.identity.store import (
    db_get_identity,
    db_get_peer,
    db_get_private_key_slug,
    db_insert_identity,
    db_lock_identity,
    db_secret_exists,
    db_upsert_peer,
)

log = structlog.get_logger(__name__)

IDENTITY_CREATED_EVENT = "module.identity_created"
PEER_REGISTERED_EVENT = "module.peer_registered"
EVENT_TYPES = frozenset({IDENTITY_CREATED_EVENT, PEER_REGISTERED_EVENT})
_IDENTITY_OBJECT_KIND = "module_identity"
_PEER_OBJECT_KIND = "enrolment_peer"
# Le chemin de l'échange de vivacité, des DEUX côtés : il entre dans la chaîne signée,
# donc l'émetteur et le vérificateur doivent en avoir la même idée au caractère près.
PEER_PING_PATH = "/api/peer/ping"
_PING_BODY = b"{}"
# Clé du verrou consultatif qui sérialise la pose de l'identité. Valeur arbitraire mais
# FIGÉE : elle n'a qu'à être unique parmi les verrous consultatifs de ce produit.
_IDENTITY_LOCK_KEY = 20261028
# L'identité naît au premier démarrage, sans humain dans la boucle. L'attribuer au compte
# d'amorçage serait un mensonge dans le journal : personne ne l'a demandée.
SYSTEM_AUTHOR = EventAuthor(LOCAL_DIRECTORY, "systeme")
# Un pair lent ne doit pas retenir une requête d'administration indéfiniment.
PEER_HTTP_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class PeerPong:
    """Ce que rend l'échange de vivacité, dans un sens comme dans l'autre."""

    module: str
    # Celle du PAIR, telle qu'il la déclare. Nulle s'il ne connaît pas son adresse publique.
    origin: str | None
    verified_key_fingerprint: str
    own_key_fingerprint: str


@dataclass(frozen=True)
class IdentityService:
    """L'identité du module : sa paire de clés, son pair apparié, ses appels signés.

    La clé privée est rangée dans la table des secrets du produit (chiffrée par
    MILES_SECRETS_KEY) et le renvoi vers sa ligne vit dans `module_identity`. Deux voies
    d'accès au dispositif des secrets, et ce n'est pas une incohérence :

    - en ÉCRITURE, le socle est appelé à son niveau magasin, parce que le secret et la
      ligne d'identité doivent être écrits dans la MÊME transaction — une panne entre les
      deux laisserait une identité qui pointe vers un secret absent. Le service du socle,
      lui, ouvre sa propre transaction ;
    - en LECTURE, c'est le service du socle qui répond, parce qu'il vérifie au passage le
      type du secret : lire comme clé de signature ce qu'un écran aurait rangé comme jeton
      git se découvrirait au premier appel refusé chez le pair.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    http: httpx.AsyncClient
    # Adresse publique du module, d'où l'origine qu'il déclare en signant. CONFIGURÉE
    # (MILES_PUBLIC_URL) et jamais lue des en-têtes : un `Host` forgé ferait signer pour
    # une origine qui n'est pas la nôtre.
    origin: str | None

    async def resolve_identity(self) -> ModuleIdentity:
        """L'identité du module, engendrée chez lui au PREMIER USAGE et jamais ensuite.

        Idempotent par construction : tout appel ultérieur relit, et ne régénère rien. Une
        régénération casserait l'appariement et imposerait de réapparier à la main, puis
        de réaffecter les devices — c'est l'interdit central du ticket 8c95ecc7.

        AU PREMIER USAGE, et non au démarrage de l'application. Divergence volontaire avec
        la première version de ce code, et elle vient d'une panne mesurée sur machine de
        test le 28/10/2026 : `dev-deploy.sh` lance la stack PUIS joue les migrations, donc
        sur une base neuve le backend démarre quand aucune table n'existe. Écrire au
        démarrage le faisait tomber en boucle de redémarrage, et son redémarrage tuait la
        commande de migration lancée dans son conteneur — le schéma restait à 7 et le
        déploiement échouait sans que la cause soit lisible. Aucun composant ne doit donc
        exiger un objet de schéma pour démarrer. Ne pas « simplifier » en revenant à un
        appel dans la durée de vie de l'application.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            await db_lock_identity(conn, _IDENTITY_LOCK_KEY)
            existante = await db_get_identity(conn)
            if existante is not None:
                return existante
            if await db_secret_exists(conn, SIGNING_KEY_SLUG):
                # Refus qui NOMME la cause, au lieu d'une violation d'unicité qui
                # avorterait la transaction et sortirait en erreur de serveur.
                raise IdentityError(
                    f"un secret porte déjà le slug « {SIGNING_KEY_SLUG} » alors que le module"
                    " n'a pas d'identité : le supprimer ou le renommer avant de redémarrer"
                )
            paire = generate_keypair()
            # La clé privée n'existe en clair que dans cette variable et le temps de ce
            # scellement : ni journal, ni valeur de retour, ni réponse HTTP ne la portent.
            sealed = self.cipher.seal(SIGNING_KEY_SLUG, Secret(paire.private_pem))
            maintenant = self.now()
            await db_insert_secret(
                conn, SIGNING_KEY_SLUG, SIGNING_KEY_LABEL, SIGNING_KEY_TYPE, sealed, maintenant
            )
            await db_declare_usage(
                conn, SIGNING_KEY_SLUG, Consumer(SIGNING_KEY_CONSUMER_KIND, SINGLETON)
            )
            identite = await db_insert_identity(
                conn, paire.public_key, SIGNING_KEY_SLUG, maintenant
            )
            await self._write_event(
                conn,
                IDENTITY_CREATED_EVENT,
                _IDENTITY_OBJECT_KIND,
                {"public_key_fingerprint": fingerprint(paire.public_key)},
            )
        log.info(
            "identite_du_module_engendree",
            public_key_fingerprint=fingerprint(identite.public_key),
        )
        return identite

    async def resolve_peer(self) -> EnrolmentPeer:
        pair = await db_get_peer(self.pool)
        if pair is None:
            raise PeerMissingError("aucun module d'enrôlement apparié")
        return pair

    async def resolve_register_peer(
        self, author: EventAuthor, base_url: str, public_key: str
    ) -> EnrolmentPeer:
        """Enregistre le module d'enrôlement apparié, ou REMPLACE celui qui existe.

        En attendant le protocole d'appariement (ticket 6a0daab6), qui déposera ces mêmes
        valeurs sans intervention humaine. Jamais un second pair : le modèle n'en admet
        qu'un, le module d'enrôlement étant l'autorité unique sur l'affectation des devices.
        """
        base_url, public_key = validate_base_url(base_url), validate_public_key(public_key)
        async with self.pool.acquire() as conn, conn.transaction():
            pair = await db_upsert_peer(conn, base_url, public_key, self.now())
            await self._write_event(
                conn,
                PEER_REGISTERED_EVENT,
                _PEER_OBJECT_KIND,
                {"base_url": base_url, "public_key_fingerprint": fingerprint(public_key)},
                author=author,
            )
        log.info(
            "pair_enregistre", base_url=base_url, public_key_fingerprint=fingerprint(public_key)
        )
        return pair

    async def resolve_private_key(self) -> Ed25519PrivateKey:
        """La clé privée, pour le temps d'une signature. Relue à CHAQUE fois, jamais gardée.

        Un cache continuerait de signer avec l'ancienne clé après un ré-appariement, et le
        symptôme apparaîtrait chez le pair — loin d'ici. Le coût est un aller-retour en
        base et une ouverture AES-GCM, sur un chemin qui n'est pas celui du trafic de masse.
        """
        identite = await self.resolve_identity()
        slug = await db_get_private_key_slug(self.pool)
        if slug is None:  # pragma: no cover - la ligne vient d'être lue juste au-dessus
            raise IdentityMissingError("aucune identité en base")
        rangee = await self.secrets.resolve_secret(slug, SIGNING_KEY_TYPE)
        privee = load_private_key(rangee.reveal())
        # Les deux moitiés doivent aller ensemble. La clé publique est celle que le pair
        # détient : signer avec une autre privée produirait des appels refusés CHEZ LUI,
        # sans que rien ici ne soit rouge. On refuse donc de signer plutôt que de mal signer.
        if encode_public_key(privee.public_key()) != identite.public_key:
            log.error(
                "identite_incoherente",
                public_key_fingerprint=fingerprint(identite.public_key),
                secret_slug=slug,
            )
            raise IdentityInconsistentError(
                "la clé privée rangée ne correspond pas à la clé publique déclarée"
            )
        return privee

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnrolmentPeer:
        """Vérifie un appel entrant, ou lève. Point d'application du fail closed de ce produit.

        Tous les refus passent par ici et sont journalisés avec l'origine DÉCLARÉE —
        validée avant d'être écrite, parce qu'avant la vérification elle n'est encore
        qu'une entrée anonyme. Ce que l'appelant apprend, lui, se limite à « refusé ».
        """
        origine_journal = origin_for_log(declared_origin)
        pair = await db_get_peer(self.pool)
        if pair is None:
            self._refuse("aucun_pair", origine_journal)
        try:
            origine = validate_origin(declared_origin or "")
        except CallSignatureError:
            self._refuse("origine_invalide", origine_journal)
        if origine != pair.base_url:
            # L'origine déclarée doit être celle du pair apparié. Sans cette comparaison,
            # le champ ne servirait qu'à décorer le journal.
            self._refuse("origine_inattendue", origine_journal)
        try:
            verify_call(
                parse_public_key(pair.public_key),
                signature,
                origin=origine,
                method=method,
                target=target,
                body=body,
            )
        except CallSignatureError as refus:
            self._refuse(refus.reason, origine_journal)
        return pair

    async def resolve_ping_peer(self) -> PeerPong:
        """Émet un appel signé vers le pair : l'autre sens du même échange."""
        pair = await self.resolve_peer()
        origine = self.origin
        if origine is None:
            raise OriginMissingError("MILES_PUBLIC_URL absente : le module ne peut pas signer")
        privee = await self.resolve_private_key()
        entete = sign_call(
            privee, origin=origine, method="POST", target=PEER_PING_PATH, body=_PING_BODY
        )
        reponse = await self.http.post(
            # `base_url` est une origine SANS chemin : la cible signée et le chemin de la
            # requête coïncident donc, ce qui est la condition pour que le pair vérifie la
            # même chaîne que celle qu'on a signée.
            f"{pair.base_url}{PEER_PING_PATH}",
            content=_PING_BODY,
            headers={
                ORIGIN_HEADER: origine,
                SIGNATURE_HEADER: entete,
                "Content-Type": "application/json",
            },
        )
        if reponse.status_code == 401:
            # Distingué d'une panne de réseau : le pair nous a répondu, et il nous a
            # refusés. C'est un désaccord de clés, donc un appariement à refaire.
            log.warning("ping_refuse_par_le_pair", base_url=pair.base_url)
            raise PeerRefusedError("le pair a refusé notre appel signé")
        if reponse.status_code != 200:
            # Il a répondu : ce n'est donc ni un problème de réseau ni un refus. Le plus
            # probable au 28/10/2026 est que son côté du protocole n'est pas encore
            # déployé — ticket 6a0daab6.
            log.warning(
                "reponse_inattendue_du_pair",
                base_url=pair.base_url,
                status_code=reponse.status_code,
            )
            raise PeerUnexpectedResponseError(reponse.status_code)
        charge = reponse.json()
        origine_du_pair = charge.get("origin")
        return PeerPong(
            module=str(charge["module"]),
            origin=None if origine_du_pair is None else str(origine_du_pair),
            verified_key_fingerprint=str(charge["verified_key_fingerprint"]),
            own_key_fingerprint=str(charge["own_key_fingerprint"]),
        )

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appel_signe_refuse", reason=reason, declared_origin=declared_origin)
        raise CallSignatureError(reason)

    async def _write_event(
        self,
        conn: Any,
        event_type: str,
        object_kind: str,
        properties: Mapping[str, Any],
        *,
        author: EventAuthor = SYSTEM_AUTHOR,
    ) -> None:
        # Jamais la clé privée, et pas même la clé publique en entier : l'empreinte suffit
        # à reconnaître une clé dans un journal, et c'est elle qu'un humain compare.
        event = NewEvent(event_type, (ObjectRef(object_kind, SINGLETON),), author, dict(properties))
        await db_write_event(conn, event, self.catalog, self.now)
