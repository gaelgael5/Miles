"""Les clés d'API de cet environnement : émission, octrois, révocation, vérification.

Décision de Gael du 02/11/2026 : « l'environnement porte une page pour gérer les clés
d'api », « une cle ouvre les portes qu'on lui octroie ». Chaque stack authentifie seule
les systèmes tiers qui déposent chez elle.

**Ce qu'une clé ouvre est relu à chaque fois, et jamais mis en cache** : une révocation ou
un retrait d'octroi vaut dès la requête suivante. Un cache ferait d'un geste de révocation
une promesse à échéance, et c'est exactement ce qu'on ne peut pas tenir sur un secret.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog
from miles_socle.apikeys.model import KEY_ID_RE, key_digest, new_key, same_digest, shown_prefix
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from environnement.apikeys.model import (
    API_KEY_OBJECT_KIND,
    GRANTS_EVENT,
    ISSUED_EVENT,
    REVOKED_EVENT,
    ApiKeyInfo,
    KeyInputError,
    KeyPrincipal,
    UnknownSourceError,
    checked_label,
    presented_key,
)
from environnement.apikeys.store import (
    StoredKey,
    db_clear_grants,
    db_insert_key,
    db_key,
    db_key_by_digest,
    db_keys,
    db_lock_key,
    db_revoke,
    db_touch,
    db_write_grants,
)
from environnement.hosting.gitstore import HostedTree
from environnement.sources.declarations import file_declared_sources

if TYPE_CHECKING:
    from asyncpg.pool import PoolConnectionProxy

    Conn = PoolConnectionProxy[asyncpg.Record]

log = structlog.get_logger(__name__)


class KeyNotFoundError(Exception):
    pass


class KeyRevokedError(Exception):
    pass


@dataclass(frozen=True)
class ApiKeysService:
    pool: asyncpg.Pool
    # L'arbre servi : c'est lui qui dit quelles sources existent. Le MÊME objet que celui
    # des storages et de l'hébergement — son verrou sérialise les gestes, et un second
    # ouvert sur le même chemin aurait son propre verrou.
    tree: HostedTree
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_declared_sources(self) -> tuple[str, ...]:
        """Les sources que la version servie déclare : ce qu'on peut octroyer.

        Relues à chaque appel, jamais mises en cache : l'arbre change quand une version
        est servie, et un cache invalidé par un autre chemin que celui-là aurait un jour
        octroyé une source qui n'est plus là.
        """
        paths = await self.tree.file_paths()
        return (await file_declared_sources(self.tree.file_text, paths)).names

    async def resolve_issue(
        self, author: EventAuthor, label: str, sources: tuple[str, ...]
    ) -> tuple[ApiKeyInfo, str]:
        """Émet une clé ; rend (clé décrite, clé en clair). La clé en clair ne se relit plus."""
        label = checked_label(label)
        demandees = await self._checked_sources(sources)
        raw, key_id = new_key(), uuid.uuid4().hex
        async with self.pool.acquire() as conn, conn.transaction():
            await db_insert_key(
                conn,
                key_id=key_id,
                label=label,
                prefix=shown_prefix(raw),
                digest=key_digest(raw),
                now=self.now(),
                author=author,
            )
            await db_write_grants(conn, key_id, demandees)
            await self._journalise(conn, ISSUED_EVENT, author, key_id, demandees)
            info = await self._described(conn, key_id)
        # Ni la clé ni son empreinte : le préfixe affiché suffit à reconnaître la ligne.
        log.info("cle_api_emise", key=key_id, prefix=info.prefix, sources=len(demandees))
        return info, raw

    async def resolve_list(self) -> list[ApiKeyInfo]:
        """Toutes les clés, révoquées comprises.

        Une clé révoquée reste visible : l'effacer rendrait son histoire illisible, et on
        ne saurait plus à qui on avait ouvert quoi.
        """
        declarees = await self.resolve_declared_sources()
        return [_info(stored, declarees) for stored in await db_keys(self.pool)]

    async def resolve_set_grants(
        self, author: EventAuthor, key_id: str, sources: tuple[str, ...]
    ) -> ApiKeyInfo:
        """Remplace les octrois ; la clé ne change pas.

        Remplace, et ne fusionne pas : fusionner ferait qu'aucun appel ne saurait RETIRER
        un octroi. Un octroi retiré vaut dès le dépôt suivant.
        """
        demandees = await self._checked_sources(sources)
        async with self.pool.acquire() as conn, conn.transaction():
            current = await self._locked(conn, key_id)
            if current.revoked_at is not None:
                # Rouvrir une porte sur une clé révoquée : elle ne redevient jamais valide,
                # et accepter l'écriture laisserait croire le contraire.
                raise KeyRevokedError(key_id)
            await db_clear_grants(conn, key_id)
            await db_write_grants(conn, key_id, demandees)
            await self._journalise(conn, GRANTS_EVENT, author, key_id, demandees)
            info = await self._described(conn, key_id)
        log.info("cle_api_octrois_changes", key=key_id, sources=len(demandees))
        return info

    async def resolve_revoke(self, author: EventAuthor, key_id: str) -> tuple[ApiKeyInfo, bool]:
        """Révoque ; rend (clé, déjà_révoquée). Rejouer ne change rien et ne journalise rien."""
        async with self.pool.acquire() as conn, conn.transaction():
            current = await self._locked(conn, key_id)
            if current.revoked_at is not None:
                return current, True
            await db_revoke(conn, key_id, self.now())
            await self._journalise(conn, REVOKED_EVENT, author, key_id, None)
            info = await self._described(conn, key_id)
        log.info("cle_api_revoquee", key=key_id)
        return info, False

    async def resolve_authenticate(self, presented: str | None, source: str) -> KeyPrincipal | None:
        """L'appelant d'une clé présentée pour déposer sur `source` ; None si elle n'ouvre pas.

        **Un seul résultat pour tous les refus**, quelle qu'en soit la raison : clé mal
        formée, inconnue, révoquée, ou valide sans octroi sur cette source. Les distinguer
        dans la réponse offrirait un oracle — savoir qu'une clé existe, ou qu'une source
        est déclarée. La raison précise est au journal, où elle sert au diagnostic.
        """
        raw = presented_key(presented)
        if raw is None:
            log.info("cle_api_refusee", raison="forme", source=source)
            return None
        digest = key_digest(raw)
        stored = await db_key_by_digest(self.pool, digest)
        if stored is None or not same_digest(stored.digest, digest):
            # L'empreinte a servi à CHERCHER ; elle est recomparée en temps constant pour
            # que la comparaison ne dise pas combien d'octets concordaient.
            log.info("cle_api_refusee", raison="inconnue", source=source)
            return None
        principal = KeyPrincipal(stored.id, stored.label, stored.sources)
        if not principal.can_write(source):
            # Distinct de « inconnue » DANS LE JOURNAL, et de nulle part ailleurs : c'est
            # ce qui permet de voir qu'un partenaire frappe à la mauvaise porte au lieu de
            # chercher une clé perdue.
            log.info("cle_api_refusee", raison="sans_octroi", key=stored.id, source=source)
            return None
        # Seulement ici : un appel refusé ne fait pas vivre une clé qui ne sert plus.
        await db_touch(self.pool, stored.id, self.now())
        return principal

    async def _checked_sources(self, sources: tuple[str, ...]) -> tuple[str, ...]:
        """Les octrois demandés, vérifiés contre la version servie. Au moins un.

        Une clé qui n'ouvre rien n'est pas un réglage, c'est un oubli : la créer « en
        attendant » laisserait une clé émise, donc un secret distribué, sans usage.
        """
        demandees = tuple(sorted(set(sources)))
        if not demandees:
            raise KeyInputError("sources", "vide")
        declarees = await self.resolve_declared_sources()
        for source in demandees:
            if source not in declarees:
                raise UnknownSourceError(source, declarees)
        return demandees

    async def _locked(self, conn: Conn, key_id: str) -> ApiKeyInfo:
        if not KEY_ID_RE.match(key_id) or not await db_lock_key(conn, key_id):
            raise KeyNotFoundError(key_id)
        return await self._described(conn, key_id)

    async def _described(self, conn: Conn, key_id: str) -> ApiKeyInfo:
        stored = await db_key(conn, key_id)
        if stored is None:
            raise KeyNotFoundError(key_id)
        return _info(stored, await self.resolve_declared_sources())

    async def _journalise(
        self,
        conn: Conn,
        kind: str,
        author: EventAuthor,
        key_id: str,
        sources: tuple[str, ...] | None,
    ) -> None:
        # Dans la MÊME transaction que la modification : aucun fait observable sans sa
        # trace, et jamais dans deux transactions (règle du système).
        properties: dict[str, Any] = {"key_id": key_id}
        if sources is not None:
            properties["sources"] = list(sources)
        event = NewEvent(kind, (ObjectRef(API_KEY_OBJECT_KIND, key_id),), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)


def _info(stored: StoredKey, declared: tuple[str, ...]) -> ApiKeyInfo:
    """Décrit une clé, en disant lesquels de ses octrois ne désignent plus rien.

    Relu à chaque lecture, comme le champ d'adresse d'une référence de compte : l'octroi
    désigne un objet de la version servie, et une version peut l'avoir retiré ou renommé
    après coup. On le SIGNALE ; on ne réécrit jamais l'octroi tout seul.
    """
    return ApiKeyInfo(
        id=stored.id,
        label=stored.label,
        prefix=stored.prefix,
        sources=stored.sources,
        missing_sources=tuple(s for s in stored.sources if s not in declared),
        created_at=stored.created_at,
        created_by=f"{stored.created_by_subject}@{stored.created_by_directory}",
        revoked_at=stored.revoked_at,
        last_used_at=stored.last_used_at,
    )
