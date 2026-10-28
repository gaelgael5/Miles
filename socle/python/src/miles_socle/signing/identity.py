"""L'identité cryptographique d'un module : sa paire de clés, engendrée chez lui.

Au socle depuis le 28/10/2026, parce qu'un DEUXIÈME produit en a besoin — le module
d'enrôlement après le module d'environnement. La règle du dépôt est d'extraire au moment
où un second usage apparaît, pas avant : c'est ce moment.

Ce qui reste au produit, et pourquoi : la table `module_identity` (le socle ne porte
aucune migration), le LIBELLÉ du secret, qui nomme le module, et tout ce qui concerne les
PAIRS — l'environnement en a exactement un, l'enrôlement en a N, et ces deux modèles n'ont
rien à partager au-delà des validateurs de forme.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
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
from miles_socle.signing.identity_model import (
    IDENTITY_CREATED_EVENT,
    SIGNING_KEY_CONSUMER_KIND,
    SIGNING_KEY_SLUG,
    SIGNING_KEY_TYPE,
    SINGLETON,
    IdentityInconsistentError,
    IdentityMissingError,
    IdentitySlugTakenError,
    ModuleIdentity,
)
from miles_socle.signing.identity_store import (
    db_get_identity,
    db_get_private_key_slug,
    db_insert_identity,
    db_lock_identity,
    db_secret_exists,
)
from miles_socle.signing.keys import (
    encode_public_key,
    fingerprint,
    generate_keypair,
    load_private_key,
)

log = structlog.get_logger(__name__)

_IDENTITY_OBJECT_KIND = "module_identity"
# Clé du verrou consultatif qui sérialise la pose de l'identité. Valeur arbitraire mais
# FIGÉE : elle n'a qu'à être unique parmi les verrous consultatifs d'un produit.
_IDENTITY_LOCK_KEY = 20261028
# L'identité naît au premier usage, sans humain dans la boucle. L'attribuer au compte
# d'amorçage serait un mensonge dans le journal : personne ne l'a demandée.
SYSTEM_AUTHOR = EventAuthor(LOCAL_DIRECTORY, "systeme")


@dataclass(frozen=True)
class ModuleIdentityService:
    """La paire de clés du module, et rien d'autre : les pairs sont l'affaire du produit.

    La clé privée est rangée dans la table des secrets du produit (chiffrée par
    MILES_SECRETS_KEY) et le renvoi vers sa ligne vit dans `module_identity`. Deux voies
    d'accès au dispositif des secrets, et ce n'est pas une incohérence :

    - en ÉCRITURE, le socle est appelé à son niveau magasin, parce que le secret et la
      ligne d'identité doivent être écrits dans la MÊME transaction — une panne entre les
      deux laisserait une identité qui pointe vers un secret absent. Le service des
      secrets, lui, ouvre sa propre transaction ;
    - en LECTURE, c'est le service qui répond, parce qu'il vérifie au passage le type du
      secret : lire comme clé de signature ce qu'un écran aurait rangé comme jeton git se
      découvrirait au premier appel refusé chez le pair.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Nomme le module dans l'écran des secrets. Seul champ qui diffère d'un produit à
    # l'autre : « une clé privée de signature » sans plus de précision serait, sur une
    # machine qui porte les trois stacks, indiscernable de celle du voisin.
    key_label: str

    async def resolve_identity(self) -> ModuleIdentity:
        """L'identité du module, engendrée chez lui au PREMIER USAGE et jamais ensuite.

        Idempotent par construction : tout appel ultérieur relit, et ne régénère rien. Une
        régénération casserait l'appariement et imposerait de réapparier à la main, puis
        de réaffecter les devices — c'est l'interdit central du ticket 6a0daab6.

        AU PREMIER USAGE, et non au démarrage de l'application. Divergence volontaire avec
        la première version de ce code, et elle vient d'une panne mesurée sur machine de
        test le 28/10/2026 : `dev-deploy.sh` lance la stack PUIS joue les migrations, donc
        sur une base neuve le backend démarre quand aucune table n'existe. Écrire au
        démarrage le faisait tomber en boucle de redémarrage, et son redémarrage tuait la
        commande de migration lancée dans son conteneur — le schéma restait en retard et
        le déploiement échouait sans que la cause soit lisible. Aucun composant ne doit
        donc exiger un objet de schéma pour démarrer. Ne pas « simplifier » en revenant à
        un appel dans la durée de vie de l'application.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            await db_lock_identity(conn, _IDENTITY_LOCK_KEY)
            existante = await db_get_identity(conn)
            if existante is not None:
                return existante
            if await db_secret_exists(conn, SIGNING_KEY_SLUG):
                # Refus qui NOMME la cause, au lieu d'une violation d'unicité qui
                # avorterait la transaction et sortirait en erreur de serveur.
                log.error("slug_de_l_identite_deja_pris", slug=SIGNING_KEY_SLUG)
                raise IdentitySlugTakenError(
                    f"un secret porte déjà le slug « {SIGNING_KEY_SLUG} » alors que le module"
                    " n'a pas d'identité : le supprimer ou le renommer"
                )
            paire = generate_keypair()
            # La clé privée n'existe en clair que dans cette variable et le temps de ce
            # scellement : ni journal, ni valeur de retour, ni réponse HTTP ne la portent.
            sealed = self.cipher.seal(SIGNING_KEY_SLUG, Secret(paire.private_pem))
            maintenant = self.now()
            await db_insert_secret(
                conn, SIGNING_KEY_SLUG, self.key_label, SIGNING_KEY_TYPE, sealed, maintenant
            )
            await db_declare_usage(
                conn, SIGNING_KEY_SLUG, Consumer(SIGNING_KEY_CONSUMER_KIND, SINGLETON)
            )
            identite = await db_insert_identity(
                conn, paire.public_key, SIGNING_KEY_SLUG, maintenant
            )
            await self.write_event(
                conn,
                IDENTITY_CREATED_EVENT,
                _IDENTITY_OBJECT_KIND,
                SINGLETON,
                {"public_key_fingerprint": fingerprint(paire.public_key)},
            )
        log.info(
            "identite_du_module_engendree",
            public_key_fingerprint=fingerprint(identite.public_key),
        )
        return identite

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

    async def write_event(
        self,
        conn: Any,
        event_type: str,
        object_kind: str,
        object_id: str,
        properties: Mapping[str, Any],
        *,
        author: EventAuthor = SYSTEM_AUTHOR,
    ) -> None:
        """Écrit un event dans la transaction de l'appelant. Exposé : les produits s'en servent.

        Jamais la clé privée, et pas même la clé publique en entier : l'empreinte suffit à
        reconnaître une clé dans un journal, et c'est elle qu'un humain compare.
        """
        event = NewEvent(event_type, (ObjectRef(object_kind, object_id),), author, dict(properties))
        await db_write_event(conn, event, self.catalog, self.now)
