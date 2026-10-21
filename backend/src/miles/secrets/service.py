from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.secrets.crypto import SecretCipher
from miles.secrets.model import (
    Consumer,
    Secret,
    SecretInUseError,
    SecretNotFoundError,
    SecretSummary,
    SecretTypeMismatchError,
    SecretUndecipherableError,
    validate_consumer,
    validate_label,
    validate_secret_type,
    validate_slug,
    validate_value,
)
from miles.secrets.store import (
    SecretsDb,
    db_declare_usage,
    db_delete_secret,
    db_fetch_sealed,
    db_get_secret,
    db_insert_secret,
    db_list_secrets,
    db_list_usages,
    db_lock_secret,
    db_release_usage,
    db_update_label,
    db_update_sealed,
)

log = structlog.get_logger(__name__)

CREATED_EVENT = "secret.created"
VALUE_REPLACED_EVENT = "secret.value_replaced"
RELABELED_EVENT = "secret.relabeled"
DELETED_EVENT = "secret.deleted"
EVENT_TYPES = frozenset({CREATED_EVENT, VALUE_REPLACED_EVENT, RELABELED_EVENT, DELETED_EVENT})
_OBJECT_KIND = "secret"


@dataclass(frozen=True)
class SecretsService:
    """Gestion et résolution des secrets de l'instance.

    Écarts VOLONTAIRES avec le standard globals « Gestion des secrets » (Gael,
    20/10/2026) : pas de coffre Harpocrate, pas de renvoi vers .env — la valeur est
    toujours en base, chiffrée —, et pas d'espace par utilisateur ni de PIN, Miles
    n'ayant que des secrets d'instance. Ce ne sont pas des oublis à compléter.
    """

    pool: asyncpg.Pool
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_create(
        self, author: EventAuthor, slug: str, label: str, secret_type: str, value: str
    ) -> SecretSummary:
        slug, label = validate_slug(slug), validate_label(label)
        secret_type, secret = validate_secret_type(secret_type), validate_value(value)
        sealed = self.cipher.seal(slug, secret)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_insert_secret(conn, slug, label, secret_type, sealed, self.now())
            await self._write_event(conn, CREATED_EVENT, slug, author, {"secret_type": secret_type})
            summary = await db_get_secret(conn, slug)
        log.info("secret_cree", slug=slug, secret_type=secret_type)
        return _found(summary, slug)

    async def resolve_replace_value(self, author: EventAuthor, slug: str, value: str) -> None:
        secret = validate_value(value)
        async with self.pool.acquire() as conn, conn.transaction():
            if await db_lock_secret(conn, slug) is None:
                raise SecretNotFoundError(slug)
            await db_update_sealed(conn, slug, self.cipher.seal(slug, secret), self.now())
            await self._write_event(conn, VALUE_REPLACED_EVENT, slug, author, {})
        log.info("secret_valeur_remplacee", slug=slug)

    async def resolve_relabel(self, author: EventAuthor, slug: str, label: str) -> SecretSummary:
        label = validate_label(label)
        async with self.pool.acquire() as conn, conn.transaction():
            if await db_lock_secret(conn, slug) is None:
                raise SecretNotFoundError(slug)
            await db_update_label(conn, slug, label, self.now())
            await self._write_event(conn, RELABELED_EVENT, slug, author, {"label": label})
            summary = await db_get_secret(conn, slug)
        log.info("secret_renomme", slug=slug)
        return _found(summary, slug)

    async def resolve_delete(self, author: EventAuthor, slug: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            secret_type = await db_lock_secret(conn, slug)
            if secret_type is None:
                raise SecretNotFoundError(slug)
            consumers = await db_list_usages(conn, slug)
            if consumers:
                log.warning("secret_suppression_refusee_utilise", slug=slug, count=len(consumers))
                raise SecretInUseError(slug, consumers)
            await db_delete_secret(conn, slug)
            await self._write_event(conn, DELETED_EVENT, slug, author, {"secret_type": secret_type})
        log.info("secret_supprime", slug=slug)

    async def resolve_list(self, secret_type: str | None) -> list[SecretSummary]:
        if secret_type is not None:
            validate_secret_type(secret_type)
        return await db_list_secrets(self.pool, secret_type)

    async def resolve_get(self, slug: str) -> SecretSummary:
        return _found(await db_get_secret(self.pool, slug), slug)

    async def resolve_secret(self, slug: str, expected_type: str | None = None) -> Secret:
        """La valeur, pour le serveur seul : aucune route HTTP n'appelle ceci.

        Sans session : un traitement de fond (terminal, dépôt git) doit pouvoir s'en servir.
        """
        found = await db_fetch_sealed(self.pool, slug)
        if found is None:
            raise SecretNotFoundError(slug)
        secret_type, sealed = found
        if expected_type is not None and secret_type != expected_type:
            raise SecretTypeMismatchError(slug, expected_type, secret_type)
        try:
            return self.cipher.open(slug, sealed)
        except SecretUndecipherableError:
            log.error("secret_indechiffrable", slug=slug)
            raise

    async def _write_event(
        self,
        conn: Any,
        event_type: str,
        slug: str,
        author: EventAuthor,
        properties: Mapping[str, Any],
    ) -> None:
        # Jamais la valeur dans l'event, ni chiffrée ni tronquée : le journal est lu
        # bien plus largement que la table des secrets.
        event = NewEvent(event_type, (ObjectRef(_OBJECT_KIND, slug),), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)


async def resolve_attach_secret(
    db: SecretsDb, slug: str, expected_type: str, consumer: Consumer
) -> None:
    """Rattache un secret à un objet, dans la transaction de cet objet.

    Vérifie à la configuration qu'il existe et qu'il a le type attendu : une erreur
    ne doit pas se découvrir à la première utilisation, souvent en tâche de fond.
    """
    validate_consumer(consumer)
    secret_type = await db_lock_secret(db, slug)
    if secret_type is None:
        raise SecretNotFoundError(slug)
    if secret_type != expected_type:
        raise SecretTypeMismatchError(slug, expected_type, secret_type)
    await db_declare_usage(db, slug, consumer)


async def resolve_detach_secret(db: SecretsDb, slug: str, consumer: Consumer) -> None:
    await db_release_usage(db, slug, validate_consumer(consumer))


def _found(summary: SecretSummary | None, slug: str) -> SecretSummary:
    if summary is None:
        raise SecretNotFoundError(slug)
    return summary
