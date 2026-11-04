from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import structlog
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.apikeys.model import Access, Grant, KeyPrincipal
from miles.oauth.clients import REVOKED_EVENT
from miles.oauth.model import GRANT_ID_RE, LOCAL_KIND, TOKEN_RE, digest
from miles.obo.service import Actor

log = structlog.get_logger(__name__)

LAST_USED_GRANULARITY = timedelta(minutes=1)


class GrantNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class GrantView:
    """Une autorisation, telle que la personne la voit dans « Mon profil »."""

    id: str
    client_label: str
    grants: dict[str, str]
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class OAuthAccess:
    """Ce que vaut un jeton d'accès présenté à /mcp/, et les autorisations d'une personne."""

    pool: asyncpg.Pool
    store: AdminAccountStore
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    def still_admin(self, kind: str, subject: str, email: str | None) -> bool:
        """La personne a-t-elle encore les droits qu'elle a délégués ?

        Recalculé à chaque appel, comme la passerelle des sessions : si le compte
        d'amorçage change dans .env, ce qu'il avait consenti ne vaut plus rien. Seul
        l'administrateur racine a des droits tant que les rôles n'existent pas.
        """
        account = self.store.account
        if account is None:
            return False
        if kind == LOCAL_KIND:
            return subject == account.username
        return email is not None and email.lower() == account.email.lower()

    async def resolve_access(self, raw: str) -> tuple[KeyPrincipal, Actor] | None:
        if not TOKEN_RE.match(raw) or not raw.startswith("mla_"):
            return None
        row = await self.pool.fetchrow(
            "SELECT g.*, c.label AS client_label, t.expires_at FROM oauth_tokens t"
            " JOIN oauth_grants g ON g.id = t.grant_id JOIN oauth_clients c ON c.id = g.client_id"
            " WHERE t.digest = $1 AND t.kind = 'access'",
            digest(raw),
        )
        if row is None or row["revoked_at"] is not None or row["expires_at"] <= self.now():
            return None
        if not self.still_admin(row["person_kind"], row["person_subject"], row["person_email"]):
            log.info("oauth_droits_perdus", grant=row["id"])
            return None
        await self._touch(row["id"])
        grants = tuple(Grant(w, Access(a)) for w, a in sorted(_grants(row).items()))
        principal = KeyPrincipal(row["id"], row["client_label"], grants, kind="oauth")
        person = EventAuthor(row["person_directory"], row["person_subject"])
        return principal, Actor(person, row["display_name"], row["person_email"])

    async def resolve_list(self, person: EventAuthor) -> list[GrantView]:
        rows = await self.pool.fetch(
            "SELECT g.id, c.label, g.grants, g.created_at, g.last_used_at FROM oauth_grants g"
            " JOIN oauth_clients c ON c.id = g.client_id WHERE g.person_directory = $1"
            " AND g.person_subject = $2 AND g.revoked_at IS NULL ORDER BY g.created_at",
            person.directory,
            person.subject,
        )
        return [
            GrantView(r["id"], r["label"], _grants(r), r["created_at"], r["last_used_at"])
            for r in rows
        ]

    async def resolve_revoke(self, person: EventAuthor, grant_id: str) -> None:
        """Révoque une de SES autorisations ; celle d'un autre est introuvable."""
        if not GRANT_ID_RE.match(grant_id):
            raise GrantNotFoundError(grant_id)
        async with self.pool.acquire() as conn, conn.transaction():
            client_id = await conn.fetchval(
                "UPDATE oauth_grants SET revoked_at = $4 WHERE id = $1 AND person_directory = $2"
                " AND person_subject = $3 AND revoked_at IS NULL RETURNING client_id",
                grant_id,
                person.directory,
                person.subject,
                self.now(),
            )
            if client_id is None:
                raise GrantNotFoundError(grant_id)
            ref = ObjectRef("oauth_client", client_id)
            event = NewEvent(REVOKED_EVENT, (ref,), person, {"grant_id": grant_id})
            await db_write_event(conn, event, self.catalog, self.now)
        log.info("oauth_autorisation_revoquee", grant=grant_id)

    async def _touch(self, grant_id: str) -> None:
        now = self.now()
        await self.pool.execute(
            "UPDATE oauth_grants SET last_used_at = $2 WHERE id = $1"
            " AND (last_used_at IS NULL OR last_used_at <= $3)",
            grant_id,
            now,
            now - LAST_USED_GRANULARITY,
        )


def _grants(row: Any) -> dict[str, str]:
    value = row["grants"]
    return dict(json.loads(value) if isinstance(value, str) else value)
