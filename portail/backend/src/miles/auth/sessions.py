from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

SESSION_COOKIE = "miles_session"
LOCAL_ADMIN_KIND = "local_admin"
OIDC_KIND = "oidc"
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
    # Annuaire OIDC de la session ; None pour le compte d'amorçage. L'identité est
    # (directory, subject) ; nom et e-mail ne servent qu'à l'affichage.
    directory: str | None = None
    display_name: str | None = None
    email: str | None = None
    # Administration racine reconnue à la connexion OIDC (ticket ad33b114). Elle tient
    # à la session et non à l'identité ; la passerelle la revérifie à chaque requête.
    root_admin: bool = False


def new_session_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    return token, token_digest(token)


def token_digest(token: str) -> bytes:
    # La base ne garde que l'empreinte : une fuite de la table ne donne aucune
    # session utilisable, le jeton lui-même ne vivant que dans le cookie.
    return hashlib.sha256(token.encode("utf-8")).digest()


async def db_create_session(
    db: DbExecutor,
    digest: bytes,
    subject_kind: str,
    subject: str,
    expires_at: datetime,
    directory: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
    root_admin: bool = False,
) -> None:
    await db.execute(
        "INSERT INTO sessions (token_digest, subject_kind, subject, expires_at, directory,"
        " display_name, email, root_admin) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        digest,
        subject_kind,
        subject,
        expires_at,
        directory,
        display_name,
        email,
        root_admin,
    )


async def db_find_session(db: DbExecutor, digest: bytes, now: datetime) -> Session | None:
    row = await db.fetchrow(
        "SELECT token_digest, subject_kind, subject, expires_at, directory, display_name, email,"
        " root_admin FROM sessions WHERE token_digest = $1 AND expires_at > $2",
        digest,
        now,
    )
    if row is None:
        return None
    return Session(
        row["token_digest"],
        row["subject_kind"],
        row["subject"],
        row["expires_at"],
        row["directory"],
        row["display_name"],
        row["email"],
        row["root_admin"],
    )


async def db_delete_session(db: DbExecutor, digest: bytes) -> None:
    await db.execute("DELETE FROM sessions WHERE token_digest = $1", digest)
