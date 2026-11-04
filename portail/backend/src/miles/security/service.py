from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.oidc.model import CONNECTOR_ID_RE, ConnectorInputError, validate_issuer
from miles_socle.secrets.model import Consumer, SecretError
from miles_socle.secrets.service import SecretsService, resolve_attach_secret, resolve_detach_secret

from miles.security.probe import Outcome, probe_keycloak

log = structlog.get_logger(__name__)

DECLARED_EVENT = "security_service.declared"
UPDATED_EVENT = "security_service.updated"
EVENT_TYPES = frozenset({DECLARED_EVENT, UPDATED_EVENT})
SECRET_TYPE = "SECURITY_SERVICE_CLIENT_SECRET"  # noqa: S105  # nom du type, pas une valeur
_REALM_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_CONSUMER_KIND = "security_service"


class SecurityServiceError(Exception):
    """Refus ; le message ne porte jamais de secret."""


class SecurityInputError(SecurityServiceError):
    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class SecurityServiceExistsError(SecurityServiceError):
    """Un seul service racine : plusieurs en parallèle n'est pas instruit (5a56c6a9)."""


class SecurityServiceNotFoundError(SecurityServiceError):
    pass


@dataclass(frozen=True)
class SecurityInput:
    base_url: str
    realm: str
    client_id: str
    client_secret_slug: str


@dataclass(frozen=True)
class SecurityService:
    id: str
    kind: str
    base_url: str
    realm: str
    client_id: str
    client_secret_slug: str
    last_check_outcome: str | None
    last_check_at: datetime | None
    created_at: datetime
    updated_at: datetime


_SELECT = (
    "SELECT id, kind, base_url, realm, client_id, client_secret_slug, last_check_outcome,"
    " last_check_at, created_at, updated_at FROM security_services"
)


def _service(row: Any) -> SecurityService:
    return SecurityService(**dict(row))


def _validate(raw: SecurityInput, allow_http: bool) -> SecurityInput:
    try:
        base_url = validate_issuer(raw.base_url, allow_http).rstrip("/")
    except ConnectorInputError:
        raise SecurityInputError("base_url") from None
    if not _REALM_RE.match(raw.realm):
        raise SecurityInputError("realm")
    client_id = raw.client_id.strip()
    if not client_id or len(client_id) > 200:
        raise SecurityInputError("client_id")
    if not raw.client_secret_slug:
        raise SecurityInputError("client_secret_slug")
    return SecurityInput(base_url, raw.realm, client_id, raw.client_secret_slug)


@dataclass(frozen=True)
class SecurityServices:
    pool: asyncpg.Pool
    http: httpx.AsyncClient
    secrets: SecretsService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    allow_http: bool

    async def resolve_list(self) -> list[SecurityService]:
        return [_service(r) for r in await self.pool.fetch(_SELECT + " ORDER BY id")]

    async def resolve_get(self, service_id: str) -> SecurityService:
        row = await self.pool.fetchrow(_SELECT + " WHERE id = $1", service_id)
        if row is None:
            raise SecurityServiceNotFoundError(service_id)
        return _service(row)

    async def resolve_declare(
        self, author: EventAuthor, service_id: str, raw: SecurityInput
    ) -> SecurityService:
        if not CONNECTOR_ID_RE.match(service_id):
            raise SecurityInputError("id")
        data = _validate(raw, self.allow_http)
        async with self.pool.acquire() as conn, conn.transaction():
            # Verrou de table court : deux déclarations simultanées ne doivent pas
            # produire deux services racine.
            await conn.execute("LOCK TABLE security_services IN EXCLUSIVE MODE")
            if await conn.fetchval("SELECT count(*) FROM security_services"):
                raise SecurityServiceExistsError
            await self._attach(conn, data.client_secret_slug, service_id)
            now = self.now()
            await conn.execute(
                "INSERT INTO security_services (id, kind, base_url, realm, client_id,"
                " client_secret_slug, created_at, updated_at)"
                " VALUES ($1, 'keycloak', $2, $3, $4, $5, $6, $6)",
                service_id,
                data.base_url,
                data.realm,
                data.client_id,
                data.client_secret_slug,
                now,
            )
            await self._event(conn, DECLARED_EVENT, service_id, author, data)
        log.info("securite_declaree", service=service_id, base_url=data.base_url)
        return await self.resolve_verify(service_id)

    async def resolve_update(
        self, author: EventAuthor, service_id: str, raw: SecurityInput
    ) -> SecurityService:
        data = _validate(raw, self.allow_http)
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(_SELECT + " WHERE id = $1 FOR UPDATE", service_id)
            if row is None:
                raise SecurityServiceNotFoundError(service_id)
            current = _service(row)
            if data.client_secret_slug != current.client_secret_slug:
                consumer = Consumer(_CONSUMER_KIND, service_id)
                await resolve_detach_secret(conn, current.client_secret_slug, consumer)
                await self._attach(conn, data.client_secret_slug, service_id)
            # Le diagnostic précédent ne vaut plus pour des coordonnées changées.
            await conn.execute(
                "UPDATE security_services SET base_url = $2, realm = $3, client_id = $4,"
                " client_secret_slug = $5, last_check_outcome = NULL, last_check_at = NULL,"
                " updated_at = $6 WHERE id = $1",
                service_id,
                data.base_url,
                data.realm,
                data.client_id,
                data.client_secret_slug,
                self.now(),
            )
            await self._event(conn, UPDATED_EVENT, service_id, author, data)
        log.info("securite_modifiee", service=service_id)
        return await self.resolve_verify(service_id)

    async def resolve_verify(self, service_id: str) -> SecurityService:
        current = await self.resolve_get(service_id)
        try:
            secret = await self.secrets.resolve_secret(current.client_secret_slug, SECRET_TYPE)
        except SecretError:
            # Secret illisible : c'est un refus d'accès vu de Miles, pas une panne réseau.
            outcome = Outcome.REFUSED
        else:
            outcome = await probe_keycloak(
                self.http,
                current.base_url,
                current.realm,
                current.client_id,
                secret,
                self.allow_http,
            )
        await self.pool.execute(
            "UPDATE security_services SET last_check_outcome = $2, last_check_at = $3"
            " WHERE id = $1",
            service_id,
            outcome.value,
            self.now(),
        )
        log.info("securite_verifiee", service=service_id, outcome=outcome.value)
        return await self.resolve_get(service_id)

    async def dependent_installations(self, service_id: str) -> int:
        # L'enrôlement n'est pas livré : aucune installation ne dépend encore du service.
        # Le compte deviendra réel avec lui ; l'avertissement de l'écran est déjà branché.
        return 0

    async def _attach(self, conn: Any, slug: str, service_id: str) -> None:
        try:
            consumer = Consumer(_CONSUMER_KIND, service_id)
            await resolve_attach_secret(conn, slug, SECRET_TYPE, consumer)
        except SecretError:
            raise SecurityInputError("client_secret_slug") from None

    async def _event(
        self, conn: Any, event_type: str, service_id: str, author: EventAuthor, data: SecurityInput
    ) -> None:
        properties = {"base_url": data.base_url, "realm": data.realm, "client_id": data.client_id}
        ref = ObjectRef("security_service", service_id)
        event = NewEvent(event_type, (ref,), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)
