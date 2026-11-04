"""La clé d'API que le back-office détient POUR LUI-MÊME, pour essayer ses propres
points d'entrée d'ingestion depuis l'écran de service.

Décision de Gael du 04/11/2026 : « la back-office se débrouille seul pour avoir une clef
en interne qui permette de consommer le service en interne parce que l'utilisateur s'est
déjà authentifié. »

**Pourquoi une VRAIE clé, et pas un demandeur fabriqué sur place.** Un essai n'a de valeur
que s'il emprunte la porte du partenaire : présentation de l'en-tête, vérification de
l'empreinte, octrois relus contre la version servie, codes de refus. Court-circuiter la
route pour appeler le service d'ingestion sauterait précisément ce qu'on veut éprouver.

**Pourquoi la valeur est gardée ici, et ne part jamais au navigateur.** Une clé ne se
relit pas : la base n'en garde que l'empreinte. Pour frapper sa propre route plusieurs
fois, le back-office doit donc détenir le clair, et le seul endroit où une valeur secrète
se range est le magasin du socle — chiffrée, avec un usage déclaré qui interdit à la base
de la supprimer. C'est le même dispositif que la clé privée de signature du module.

**Ce que ça change dans ce qu'on promet, et qui est écrit dans l'article publié** : une
session d'écran provoque désormais un dépôt, indirectement. Pour un appelant tiers rien ne
bouge — le point d'entrée exige toujours une clé.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg
import structlog
from miles_socle.apikeys.model import key_digest
from miles_socle.events.model import EventAuthor
from miles_socle.secrets.model import Consumer, Secret, SecretNotFoundError
from miles_socle.secrets.service import SecretsService, resolve_attach_secret

from environnement.apikeys.service import ApiKeysService
from environnement.apikeys.store import db_key_of_digest

log = structlog.get_logger(__name__)

# Le secret qui porte la valeur de la clé. Le slug est stable : c'est lui qui la retrouve
# d'un démarrage à l'autre, et le changer perdrait la clé en place.
SELF_KEY_SLUG = "ingestion-back-office"
SELF_KEY_TYPE = "INGEST_BACKOFFICE_KEY"
# L'usage déclaré : c'est lui qui interdit à la base de supprimer le secret. Même
# mécanisme que pour la clé de signature du module.
SELF_KEY_CONSUMER_KIND = "ingestion_self_key"
SELF_KEY_CONSUMER_ID = "singleton"
# Le libellé de la CLÉ, celui qui s'affiche dans la page des clés et dans le journal des
# appels. Il doit dire d'où vient le dépôt : un essai depuis l'écran ne doit pas se lire
# comme le dépôt d'un partenaire.
SELF_KEY_LABEL = "Back-office (essais depuis l'écran)"
SELF_KEY_STORE_LABEL = "Clé d'API du back-office pour ses propres essais d'ingestion"


class SelfKeyRevokedError(Exception):
    """Quelqu'un a révoqué la clé du back-office.

    Levée plutôt que réémise en silence : la révocation est un geste délibéré, et la
    reprendre à l'insu de celui qui l'a fait annulerait sa décision. L'écran le dit, et
    une réémission demande une action explicite.
    """

    def __init__(self, key_id: str) -> None:
        super().__init__(key_id)
        self.key_id = key_id


@dataclass(frozen=True)
class SelfKeyService:
    """Rend une clé utilisable, en l'émettant au premier besoin."""

    pool: asyncpg.Pool
    keys: ApiKeysService
    secrets: SecretsService

    async def resolve_usable(self, author: EventAuthor) -> Secret:
        """La valeur de la clé du back-office, émise si elle n'existe pas encore.

        Émise au premier besoin et non au démarrage : une stack qui ne sert aucune version
        n'a aucune source à octroyer, donc rien à quoi rattacher une clé. Et la poser
        d'avance ferait exister un justificatif que personne n'a demandé.
        """
        try:
            rangee = await self.secrets.resolve_secret(SELF_KEY_SLUG, SELF_KEY_TYPE)
        except SecretNotFoundError:
            return await self._issue(author, replace=False)
        stored = await db_key_of_digest(self.pool, key_digest(rangee.reveal()))
        if stored is None:
            # La valeur est rangée mais aucune clé ne lui correspond : la ligne a été
            # effacée, ou la base a été recréée sous un secret conservé. On réémet plutôt
            # que de rendre un justificatif qui sera refusé sans qu'on sache pourquoi.
            log.warning("cle_du_back_office_sans_ligne", slug=SELF_KEY_SLUG)
            return await self._issue(author, replace=True)
        if stored.revoked_at is not None:
            raise SelfKeyRevokedError(stored.id)
        await self._align_grants(author, stored.id, stored.sources)
        return rangee

    async def resolve_reissue(self, author: EventAuthor) -> Secret:
        """Réémet une clé, après une révocation. Geste EXPLICITE de l'administrateur.

        L'ancienne reste révoquée et visible : effacer son histoire ferait perdre la trace
        des dépôts qu'elle a portés.
        """
        return await self._issue(author, replace=True)

    async def _issue(self, author: EventAuthor, *, replace: bool) -> Secret:
        """Émet la clé, octroyée sur toutes les sources déclarées, et range sa valeur."""
        sources = await self.keys.resolve_declared_sources()
        info, raw = await self.keys.resolve_issue(author, SELF_KEY_LABEL, sources)
        try:
            await self._store(author, raw, replace=replace)
        except Exception:
            # La clé existe et sa valeur n'est nulle part : elle ne servira jamais, et la
            # laisser active ferait traîner un justificatif que personne ne détient. On la
            # révoque avant de relayer la panne — l'appelant doit la voir.
            log.error("valeur_de_la_cle_du_back_office_non_rangee", key=info.id)
            await self.keys.resolve_revoke(author, info.id)
            raise
        log.info("cle_du_back_office_emise", key=info.id, prefix=info.prefix)
        return Secret(raw)

    async def _store(self, author: EventAuthor, raw: str, *, replace: bool) -> None:
        """Range la valeur dans le magasin, et déclare son usage au premier passage.

        L'usage n'est déclaré qu'à la création : le redéclarer au remplacement n'ajoute
        rien, et le magasin refuse déjà la suppression d'un secret employé.
        """
        if replace:
            await self.secrets.resolve_replace_value(author, SELF_KEY_SLUG, raw)
            return
        await self.secrets.resolve_create(
            author, SELF_KEY_SLUG, SELF_KEY_STORE_LABEL, SELF_KEY_TYPE, raw
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await resolve_attach_secret(
                conn,
                SELF_KEY_SLUG,
                SELF_KEY_TYPE,
                Consumer(SELF_KEY_CONSUMER_KIND, SELF_KEY_CONSUMER_ID),
            )

    async def _align_grants(
        self, author: EventAuthor, key_id: str, granted: tuple[str, ...]
    ) -> None:
        """Réoctroie la clé sur les sources que la version servie déclare, si elles ont
        changé.

        Comparé avant d'écrire, et non réécrit à chaque essai : un remplacement d'octrois
        écrit un event, et un journal qui répète le même geste à chaque clic ne se lit
        plus. C'est le DELTA qui parle — leçon du 02/11/2026 sur les opérations
        idempotentes.
        """
        declarees = await self.keys.resolve_declared_sources()
        if set(declarees) == set(granted):
            return
        log.info("octrois_du_back_office_realignes", key=key_id, sources=len(declarees))
        await self.keys.resolve_set_grants(author, key_id, declarees)
