from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

SESSION_COOKIE = "miles_session"
LOCAL_ADMIN_KIND = "local_admin"
_TOKEN_BYTES = 32


class DbExecutor(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class Session:
    digest: bytes
    subject_kind: str
    subject: str
    expires_at: datetime


def new_session_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return token, token_digest(token)


def token_digest(token: str) -> bytes:
    # La base ne garde que l'empreinte : une fuite de la table ne donne aucune
    # session utilisable, le jeton lui-même ne vivant que dans le cookie.
    return hashlib.sha256(token.encode("utf-8")).digest()


async def db_create_session(
    db: DbExecutor, digest: bytes, subject_kind: str, subject: str, expires_at: datetime
) -> None:
    await db.execute(
        "INSERT INTO sessions (token_digest, subject_kind, subject, expires_at)"
        " VALUES ($1, $2, $3, $4)",
        digest,
        subject_kind,
        subject,
        expires_at,
    )


async def db_find_session(db: DbExecutor, digest: bytes, now: datetime) -> Session | None:
    row = await db.fetchrow(
        "SELECT token_digest, subject_kind, subject, expires_at FROM sessions"
        " WHERE token_digest = $1 AND expires_at > $2",
        digest,
        now,
    )
    if row is None:
        return None
    return Session(row["token_digest"], row["subject_kind"], row["subject"], row["expires_at"])


async def db_delete_session(db: DbExecutor, digest: bytes) -> None:
    await db.execute("DELETE FROM sessions WHERE token_digest = $1", digest)
