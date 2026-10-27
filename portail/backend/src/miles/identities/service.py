from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import httpx
import structlog
from miles_socle.events.journal import EventDb, db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.secrets.crypto import Sealed, SecretCipher
from miles_socle.secrets.model import Secret

from miles.git.forge import RepositoryUrlError, parse_repository
from miles.identities.forge_api import (
    EmailOrigin,
    ForgeAccount,
    api_root,
    can_write,
    fetch_account,
)

log = structlog.get_logger(__name__)

REGISTERED_EVENT = "user.git_identity_registered"
REMOVED_EVENT = "user.git_identity_removed"
EVENT_TYPES = frozenset({REGISTERED_EVENT, REMOVED_EVENT})
MAX_TOKEN_LENGTH = 1024


class ConnectionNotFoundError(Exception):
    pass


class EmptyTokenError(Exception):
    pass


class TokenInUseError(Exception):
    """Le PAT sert une prise de main en cours (9def0adc, critère 12) : on nomme laquelle."""

    def __init__(self, workspace_id: str, slug: str) -> None:
        super().__init__(f"prise de main en cours sur {workspace_id}/{slug}")
        self.workspace_id, self.slug = workspace_id, slug


@dataclass(frozen=True)
class RepositoryCheck:
    workspace_id: str
    workspace_name: str
    # None : la forge n'a pas répondu ; à revérifier plus tard.
    can_write: bool | None


@dataclass(frozen=True)
class GitIdentity:
    connection_id: str
    connection_label: str
    base_url: str
    # None : aucune identité enregistrée pour cette connexion.
    account: ForgeAccount | None = None
    repositories: tuple[RepositoryCheck, ...] = ()
    verified_at: datetime | None = None


def _aad(viewer: EventAuthor, connection_id: str) -> str:
    # Données associées propres à la ligne : un chiffré recopié sur une autre personne
    # ou une autre connexion ne s'ouvre plus.
    return f"git-identity/{viewer.directory}/{viewer.subject}/{connection_id}"


@dataclass(frozen=True)
class GitIdentitiesService:
    """Identité git personnelle, une par connexion git (story 033e5ff3).

    Le jeton est chiffré par la clé de l'instance, pas par un code de la personne :
    Miles s'en servira aussi sans elle, pour ranger son travail quand l'administrateur
    la déverrouille (story fd1eb7da). Un secret ouvert seulement en sa présence
    échouerait précisément à ce moment-là.
    """

    pool: asyncpg.Pool
    cipher: SecretCipher
    http: httpx.AsyncClient
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    extra_git_hosts: Sequence[str] = field(default=())

    async def resolve_list(self, viewer: EventAuthor) -> list[GitIdentity]:
        rows = await self.pool.fetch(
            "SELECT c.id, c.label, c.base_url, i.login, i.name, i.email, i.email_origin,"
            " i.repositories, i.verified_at FROM git_connections c"
            " LEFT JOIN user_git_identities i ON i.connection_id = c.id"
            " AND i.viewer_directory = $1 AND i.viewer_subject = $2 ORDER BY c.label, c.id",
            viewer.directory,
            viewer.subject,
        )
        return [_identity(r) for r in rows]

    async def resolve_register(
        self, viewer: EventAuthor, connection_id: str, raw_token: str
    ) -> GitIdentity:
        """Vérifie le jeton auprès de la forge, puis le retient.

        Un jeton refusé n'est pas gardé : rien n'est écrit avant la réponse de la forge.
        """
        token = Secret(raw_token.strip())
        if not token.reveal() or len(token.reveal()) > MAX_TOKEN_LENGTH:
            raise EmptyTokenError
        connection = await self.pool.fetchrow(
            "SELECT id, label, base_url FROM git_connections WHERE id = $1", connection_id
        )
        if connection is None:
            raise ConnectionNotFoundError(connection_id)
        root = api_root(connection["base_url"], self.extra_git_hosts)
        account = await fetch_account(self.http, root, token)
        checks = await self._checks(root, token, connection_id)
        sealed = self.cipher.seal(_aad(viewer, connection_id), token)
        verified_at = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                _UPSERT, *_row(viewer, connection_id, sealed, account, checks), verified_at
            )
            await self._event(conn, viewer, REGISTERED_EVENT, connection_id, account.login)
        log.info("identite_git_enregistree", connection=connection_id, login=account.login)
        return GitIdentity(
            connection_id, connection["label"], connection["base_url"], account, checks, verified_at
        )

    async def resolve_remove(self, viewer: EventAuthor, connection_id: str) -> bool:
        """Retire le jeton ; rend False s'il n'y en avait pas (rejeu sans effet)."""
        async with self.pool.acquire() as conn, conn.transaction():
            # Verrouillée dans la transaction du retrait : une prise de main ne peut pas
            # s'appuyer sur ce jeton entre la vérification et la suppression.
            held = await conn.fetchrow(
                "SELECT workspace_id, slug FROM branch_holds WHERE holder_directory = $1"
                " AND holder_subject = $2 AND connection_id = $3 FOR UPDATE",
                viewer.directory,
                viewer.subject,
                connection_id,
            )
            if held is not None:
                # Sans lui, les commits locaux ne pourraient plus être publiés (critère 12).
                raise TokenInUseError(held["workspace_id"], held["slug"])
            removed = await conn.fetchval(
                "DELETE FROM user_git_identities WHERE viewer_directory = $1"
                " AND viewer_subject = $2 AND connection_id = $3 RETURNING login",
                viewer.directory,
                viewer.subject,
                connection_id,
            )
            if removed is None:
                return False
            await self._event(conn, viewer, REMOVED_EVENT, connection_id, str(removed))
        return True

    async def resolve_token(self, viewer: EventAuthor, connection_id: str) -> Secret | None:
        """Jeton de la personne pour cette connexion, au point d'injection d'un geste git."""
        row = await self.pool.fetchrow(
            "SELECT key_version, nonce, ciphertext FROM user_git_identities"
            " WHERE viewer_directory = $1 AND viewer_subject = $2 AND connection_id = $3",
            viewer.directory,
            viewer.subject,
            connection_id,
        )
        if row is None:
            return None
        sealed = Sealed(row["key_version"], row["nonce"], row["ciphertext"])
        return self.cipher.open(_aad(viewer, connection_id), sealed)

    async def resolve_signature(
        self, viewer: EventAuthor, connection_id: str
    ) -> tuple[str, str] | None:
        """(nom, e-mail) lus sur le compte de la forge : l'auteur git de la personne."""
        row = await self.pool.fetchrow(
            "SELECT name, email FROM user_git_identities"
            " WHERE viewer_directory = $1 AND viewer_subject = $2 AND connection_id = $3",
            viewer.directory,
            viewer.subject,
            connection_id,
        )
        return None if row is None else (str(row["name"]), str(row["email"]))

    async def _checks(
        self, root: str, token: Secret, connection_id: str
    ) -> tuple[RepositoryCheck, ...]:
        rows = await self.pool.fetch(
            "SELECT id, name, repo_url FROM workspaces"
            " WHERE git_connection_id = $1 AND repo_url IS NOT NULL ORDER BY name, id",
            connection_id,
        )
        checks = []
        for row in rows:
            try:
                repo = parse_repository(row["repo_url"], self.extra_git_hosts)
            except RepositoryUrlError:
                checks.append(RepositoryCheck(row["id"], row["name"], None))
                continue
            allowed = await can_write(self.http, root, token, repo.owner, repo.name)
            checks.append(RepositoryCheck(row["id"], row["name"], allowed))
        return tuple(checks)

    async def _event(
        self,
        conn: EventDb,
        viewer: EventAuthor,
        kind: str,
        connection_id: str,
        login: str,
    ) -> None:
        # Le login et la connexion suffisent à dire qui a fait quoi ; le jeton n'y va jamais.
        properties = {"connection": connection_id, "login": login}
        event = NewEvent(kind, (ObjectRef("git_connection", connection_id),), viewer, properties)
        await db_write_event(conn, event, self.catalog, self.now)


_UPSERT = (
    "INSERT INTO user_git_identities (viewer_directory, viewer_subject, connection_id,"
    " key_version, nonce, ciphertext, login, name, email, email_origin, repositories,"
    " verified_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12)"
    " ON CONFLICT (viewer_directory, viewer_subject, connection_id) DO UPDATE SET"
    " key_version = EXCLUDED.key_version, nonce = EXCLUDED.nonce,"
    " ciphertext = EXCLUDED.ciphertext, login = EXCLUDED.login, name = EXCLUDED.name,"
    " email = EXCLUDED.email, email_origin = EXCLUDED.email_origin,"
    " repositories = EXCLUDED.repositories, verified_at = EXCLUDED.verified_at"
)


def _row(
    viewer: EventAuthor,
    connection_id: str,
    sealed: Sealed,
    account: ForgeAccount,
    checks: tuple[RepositoryCheck, ...],
) -> tuple[object, ...]:
    repositories = json.dumps(
        [
            {
                "workspace_id": c.workspace_id,
                "workspace_name": c.workspace_name,
                "can_write": c.can_write,
            }
            for c in checks
        ]
    )
    return (
        viewer.directory,
        viewer.subject,
        connection_id,
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
        account.login,
        account.name,
        account.email,
        account.email_origin.value,
        repositories,
    )


def _identity(row: asyncpg.Record) -> GitIdentity:
    if row["login"] is None:
        return GitIdentity(row["id"], row["label"], row["base_url"])
    account = ForgeAccount(
        row["login"], row["name"], row["email"], EmailOrigin(row["email_origin"])
    )
    checks = tuple(
        RepositoryCheck(c["workspace_id"], c["workspace_name"], c["can_write"])
        for c in json.loads(row["repositories"])
    )
    return GitIdentity(
        row["id"], row["label"], row["base_url"], account, checks, row["verified_at"]
    )
