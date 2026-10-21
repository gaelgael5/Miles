from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.access import GitAccess
from miles.git.rights import SUFFIX_RE
from miles.git.selfsigned import VALIDITY_MAX_DAYS, VALIDITY_MIN_DAYS, generate_self_signed
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.model import (
    CERT_PEM_MAX,
    CERTIFICATE_CREATED,
    CERTIFICATE_DELETED,
    CERTIFICATE_REPLACED,
    CLIENT_KEY_TYPE,
    CertificateRef,
    ClientCertificateRecord,
    GitAccessConflictError,
    GitAccessInputError,
    GitAccessInUseError,
    GitAccessNotFoundError,
    validate_id,
    validate_label,
)
from miles.gitaccess.resolver import AccessResolver
from miles.secrets.model import Consumer, SecretError, SecretSlugTakenError
from miles.secrets.service import resolve_attach_secret, resolve_detach_secret

log = structlog.get_logger(__name__)

_CONSUMER_KIND = "client_certificate"
_SELECT = (
    "SELECT k.id, k.label, k.cert_pem, k.key_secret_slug, k.not_after, k.created_at,"
    " k.updated_at, coalesce(array_agg(c.id ORDER BY c.id) FILTER (WHERE c.id IS NOT NULL),"
    " '{}') AS connections FROM client_certificates k"
    " LEFT JOIN git_connections c ON c.certificate_id = k.id"
)


def _record(row: Any) -> ClientCertificateRecord:
    data = dict(row)
    data["connections"] = tuple(data["connections"])
    return ClientCertificateRecord(**data)


@dataclass(frozen=True)
class CertificatesService:
    """Certificats clients de la racine (story 7d7dfb41), choisis ensuite par les connexions."""

    pool: asyncpg.Pool
    resolver: AccessResolver
    verifier: DependentsVerifier
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self) -> list[ClientCertificateRecord]:
        rows = await self.pool.fetch(_SELECT + " GROUP BY k.id ORDER BY k.label, k.id")
        return [_record(r) for r in rows]

    async def resolve_get(self, certificate_id: str) -> ClientCertificateRecord:
        row = await self.pool.fetchrow(_SELECT + " WHERE k.id = $1 GROUP BY k.id", certificate_id)
        if row is None:
            raise GitAccessNotFoundError("certificat")
        return _record(row)

    async def resolve_create(
        self, author: EventAuthor, certificate_id: str, label: str, ref: CertificateRef
    ) -> tuple[ClientCertificateRecord, bool]:
        """Déclare un certificat ; rend (certificat, déjà_là). Rejeu à l'identique : sans effet."""
        certificate_id, label = validate_id(certificate_id), validate_label(label)
        _check_pem_size(ref)
        existing = await self.pool.fetchrow(
            "SELECT label, cert_pem, key_secret_slug FROM client_certificates WHERE id = $1",
            certificate_id,
        )
        if existing is not None:
            if tuple(existing) == (label, ref.cert_pem, ref.key_secret_slug):
                return await self.resolve_get(certificate_id), True
            raise GitAccessConflictError("identifiant_pris")
        checked = await self.resolver.certificate(ref)
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await _attach_key(conn, ref.key_secret_slug, certificate_id)
                await conn.execute(
                    "INSERT INTO client_certificates (id, label, cert_pem, key_secret_slug,"
                    " not_after, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $6)",
                    certificate_id,
                    label,
                    ref.cert_pem,
                    ref.key_secret_slug,
                    checked.not_after,
                    self.now(),
                )
                properties = {"not_after": checked.not_after.isoformat()}
                await self._event(conn, CERTIFICATE_CREATED, certificate_id, author, properties)
        except asyncpg.UniqueViolationError:
            raise GitAccessConflictError("identifiant_pris") from None
        log.info("certificat_client_declare", certificate=certificate_id)
        return await self.resolve_get(certificate_id), False

    async def resolve_generate(
        self, author: EventAuthor, certificate_id: str, label: str, days: int
    ) -> ClientCertificateRecord:
        """Génère clé et certificat auto-signé (décision du 21/10/2026, story 9265f111).

        La clé naît dans Miles et va droit au socle des secrets : elle ne passe par aucun
        copier-coller. Secret et certificat s'écrivent dans une seule transaction, pour
        qu'un identifiant déjà pris ne laisse pas de clé orpheline.
        Pas de rejeu « sans effet » : deux générations ne produisent jamais la même clé.
        """
        certificate_id, label = validate_id(certificate_id), validate_label(label)
        if not VALIDITY_MIN_DAYS <= days <= VALIDITY_MAX_DAYS:
            raise GitAccessInputError("validity_days")
        generated = generate_self_signed(label, days, self.now())
        key_slug = _generated_key_slug(certificate_id)
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await self.resolver.secrets.db_create(
                    conn, author, key_slug, f"Clé de {label}", CLIENT_KEY_TYPE, generated.key
                )
                await _attach_key(conn, key_slug, certificate_id)
                await conn.execute(
                    "INSERT INTO client_certificates (id, label, cert_pem, key_secret_slug,"
                    " not_after, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $6)",
                    certificate_id,
                    label,
                    generated.cert_pem,
                    key_slug,
                    generated.not_after,
                    self.now(),
                )
                properties = {"not_after": generated.not_after.isoformat(), "generated": True}
                await self._event(conn, CERTIFICATE_CREATED, certificate_id, author, properties)
        except asyncpg.UniqueViolationError:
            raise GitAccessConflictError("identifiant_pris") from None
        except SecretSlugTakenError:
            # Le secret s'écrit avant le certificat (clé étrangère) : regénérer sous un
            # identifiant pris bute d'abord sur le slug de sa clé. On nomme la vraie cause.
            taken = await self.pool.fetchval(
                "SELECT 1 FROM client_certificates WHERE id = $1", certificate_id
            )
            raise GitAccessConflictError("identifiant_pris" if taken else "cle_existante") from None
        log.info("certificat_client_genere", certificate=certificate_id, days=days)
        return await self.resolve_get(certificate_id)

    async def resolve_replace(
        self,
        author: EventAuthor,
        certificate_id: str,
        label: str,
        ref: CertificateRef,
        suffix: str,
    ) -> ClientCertificateRecord:
        """Remplace certificat et clé, après avoir éprouvé chaque workspace qui s'en sert.

        Le remplacement ne s'applique que si tous gardent leurs cinq droits : sinon on
        couperait l'accès au dépôt de workspaces qui fonctionnaient.
        """
        if not SUFFIX_RE.match(suffix):
            raise GitAccessInputError("verification_suffix")
        label = validate_label(label)
        _check_pem_size(ref)
        current = await self.resolve_get(certificate_id)
        not_after = (await self.resolver.certificate(ref)).not_after
        rows = await self.pool.fetch(
            "SELECT id, token_secret_slug FROM git_connections WHERE certificate_id = $1",
            certificate_id,
        )
        tokens: dict[str, str | None] = {r["id"]: r["token_secret_slug"] for r in rows}

        async def access_for(connection_id: str) -> GitAccess:
            return await self.resolver.access(tokens[connection_id], ref)

        reports = await self.verifier.resolve_verify(
            author, current.connections, access_for, suffix
        )
        async with self.pool.acquire() as conn, conn.transaction():
            consumer = Consumer(_CONSUMER_KIND, certificate_id)
            await resolve_detach_secret(conn, current.key_secret_slug, consumer)
            await _attach_key(conn, ref.key_secret_slug, certificate_id)
            await conn.execute(
                "UPDATE client_certificates SET label = $2, cert_pem = $3, key_secret_slug = $4,"
                " not_after = $5, updated_at = $6 WHERE id = $1",
                certificate_id,
                label,
                ref.cert_pem,
                ref.key_secret_slug,
                not_after,
                self.now(),
            )
            await self.verifier.db_store_reports(conn, reports)
            properties = {"not_after": not_after.isoformat(), "workspaces": len(reports)}
            await self._event(conn, CERTIFICATE_REPLACED, certificate_id, author, properties)
        log.info("certificat_client_remplace", certificate=certificate_id, workspaces=len(reports))
        return await self.resolve_get(certificate_id)

    async def resolve_delete(self, author: EventAuthor, certificate_id: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            key = await conn.fetchval(
                "SELECT key_secret_slug FROM client_certificates WHERE id = $1 FOR UPDATE",
                certificate_id,
            )
            if key is None:
                raise GitAccessNotFoundError("certificat")
            users = await conn.fetch(
                "SELECT id FROM git_connections WHERE certificate_id = $1 ORDER BY id",
                certificate_id,
            )
            if users:
                raise GitAccessInUseError(tuple(r["id"] for r in users))
            await conn.execute("DELETE FROM client_certificates WHERE id = $1", certificate_id)
            await resolve_detach_secret(conn, key, Consumer(_CONSUMER_KIND, certificate_id))
            await self._event(conn, CERTIFICATE_DELETED, certificate_id, author, {})
        log.info("certificat_client_supprime", certificate=certificate_id)

    async def _event(
        self,
        conn: Any,
        event_type: str,
        certificate_id: str,
        author: EventAuthor,
        properties: dict[str, Any],
    ) -> None:
        # Jamais la clé ni le certificat dans l'event : l'échéance suffit à l'exploitation.
        objects = (ObjectRef(_CONSUMER_KIND, certificate_id),)
        event = NewEvent(event_type, objects, author, properties)
        await db_write_event(conn, event, self.catalog, self.now)


def _generated_key_slug(certificate_id: str) -> str:
    # Le slug d'un secret est borné à 63 caractères comme l'identifiant : on tronque
    # l'identifiant pour garder le suffixe qui dit à quoi sert le secret.
    return f"{certificate_id[:59]}-cle"


def _check_pem_size(ref: CertificateRef) -> None:
    if not ref.cert_pem.strip() or len(ref.cert_pem) > CERT_PEM_MAX:
        raise GitAccessInputError("cert_pem", "illisible")


async def _attach_key(conn: Any, slug: str, certificate_id: str) -> None:
    # Le certificat tient sa clé : le socle refusera de supprimer le secret tant qu'il
    # sert, au lieu de laisser une connexion sans accès découverte au premier usage.
    try:
        await resolve_attach_secret(
            conn, slug, CLIENT_KEY_TYPE, Consumer(_CONSUMER_KIND, certificate_id)
        )
    except SecretError:
        raise GitAccessInputError("key_secret_slug") from None
