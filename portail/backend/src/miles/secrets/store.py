from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import asyncpg

from miles.secrets.crypto import Sealed
from miles.secrets.model import Consumer, SecretSlugTakenError, SecretSummary


class SecretsDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


# Aucune requête de ce module ne lit nonce ou ciphertext, sauf db_fetch_sealed : les
# listes et les fiches ne transportent jamais la valeur, même chiffrée.
_SUMMARY = """
SELECT s.slug, s.label, s.secret_type, s.created_at, s.updated_at,
       coalesce(array_agg(u.consumer_kind ORDER BY u.consumer_kind, u.consumer_id)
                FILTER (WHERE u.consumer_kind IS NOT NULL), '{}') AS consumer_kinds,
       coalesce(array_agg(u.consumer_id ORDER BY u.consumer_kind, u.consumer_id)
                FILTER (WHERE u.consumer_kind IS NOT NULL), '{}') AS consumer_ids
FROM secrets s LEFT JOIN secret_usages u ON u.secret_slug = s.slug
"""


def _summary(row: Any) -> SecretSummary:
    consumers = tuple(
        Consumer(kind, ident)
        for kind, ident in zip(row["consumer_kinds"], row["consumer_ids"], strict=True)
    )
    return SecretSummary(
        row["slug"],
        row["label"],
        row["secret_type"],
        row["created_at"],
        row["updated_at"],
        consumers,
    )


async def db_insert_secret(
    db: SecretsDb, slug: str, label: str, secret_type: str, sealed: Sealed, now: datetime
) -> None:
    # L'unicité se joue à l'écriture, pas par une lecture préalable : deux créations
    # concurrentes du même slug passeraient toutes deux une vérification.
    try:
        await db.execute(
            "INSERT INTO secrets (slug, label, secret_type, key_version, nonce, ciphertext,"
            " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)",
            slug,
            label,
            secret_type,
            sealed.key_version,
            sealed.nonce,
            sealed.ciphertext,
            now,
        )
    except asyncpg.UniqueViolationError:
        raise SecretSlugTakenError(slug) from None


async def db_list_secrets(db: SecretsDb, secret_type: str | None) -> list[SecretSummary]:
    rows = await db.fetch(
        _SUMMARY + " WHERE ($1::text IS NULL OR s.secret_type = $1)"
        " GROUP BY s.slug ORDER BY s.label, s.slug",
        secret_type,
    )
    return [_summary(row) for row in rows]


async def db_get_secret(db: SecretsDb, slug: str) -> SecretSummary | None:
    row = await db.fetchrow(_SUMMARY + " WHERE s.slug = $1 GROUP BY s.slug", slug)
    return None if row is None else _summary(row)


async def db_fetch_sealed(db: SecretsDb, slug: str) -> tuple[str, Sealed] | None:
    row = await db.fetchrow(
        "SELECT secret_type, key_version, nonce, ciphertext FROM secrets WHERE slug = $1", slug
    )
    if row is None:
        return None
    return row["secret_type"], Sealed(row["key_version"], row["nonce"], row["ciphertext"])


async def db_lock_secret(db: SecretsDb, slug: str) -> str | None:
    """Verrouille la ligne pour la transaction en cours ; rend son type, ou None.

    FOR UPDATE entre en conflit avec le verrou que pose la clé étrangère d'une
    déclaration d'usage concurrente : la suppression et l'usage se sérialisent.
    """
    row = await db.fetchrow("SELECT secret_type FROM secrets WHERE slug = $1 FOR UPDATE", slug)
    return None if row is None else str(row["secret_type"])


async def db_update_sealed(db: SecretsDb, slug: str, sealed: Sealed, now: datetime) -> None:
    await db.execute(
        "UPDATE secrets SET key_version = $2, nonce = $3, ciphertext = $4, updated_at = $5"
        " WHERE slug = $1",
        slug,
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
        now,
    )


async def db_update_label(db: SecretsDb, slug: str, label: str, now: datetime) -> None:
    await db.execute(
        "UPDATE secrets SET label = $2, updated_at = $3 WHERE slug = $1", slug, label, now
    )


async def db_list_usages(db: SecretsDb, slug: str) -> tuple[Consumer, ...]:
    rows = await db.fetch(
        "SELECT consumer_kind, consumer_id FROM secret_usages WHERE secret_slug = $1"
        " ORDER BY consumer_kind, consumer_id",
        slug,
    )
    return tuple(Consumer(r["consumer_kind"], r["consumer_id"]) for r in rows)


async def db_delete_secret(db: SecretsDb, slug: str) -> None:
    await db.execute("DELETE FROM secrets WHERE slug = $1", slug)


async def db_declare_usage(db: SecretsDb, slug: str, consumer: Consumer) -> None:
    # Idempotent : un consommateur qui réenregistre sa configuration redéclare
    # le même usage sans erreur.
    await db.execute(
        "INSERT INTO secret_usages (secret_slug, consumer_kind, consumer_id)"
        " VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        slug,
        consumer.kind,
        consumer.id,
    )


async def db_release_usage(db: SecretsDb, slug: str, consumer: Consumer) -> None:
    await db.execute(
        "DELETE FROM secret_usages WHERE secret_slug = $1 AND consumer_kind = $2"
        " AND consumer_id = $3",
        slug,
        consumer.kind,
        consumer.id,
    )
