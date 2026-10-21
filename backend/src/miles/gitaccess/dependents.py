from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.access import GitAccess
from miles.git.forge import parse_repository, repository_under
from miles.git.rights import AccessReport, run_access_check
from miles.gitaccess.model import DependentCheckFailedError, DependentOutsideError
from miles.workspaces.model import CHECKED_EVENT, check_summary, report_json

AccessFor = Callable[[str], Awaitable[GitAccess]]


@dataclass(frozen=True)
class DependentsVerifier:
    """Éprouve les cinq droits de chaque workspace touché par un changement d'accès.

    Changer le PAT ou l'adresse d'une connexion vaut pour TOUS les
    workspaces qui s'en servent : le changement n'est appliqué que si chacun garde ses
    cinq droits (décision du 18/10/2026, étendue le 21/10). Sinon un workspace qui
    fonctionnait casserait plus tard, au milieu d'une opération sans rapport apparent.
    """

    pool: asyncpg.Pool
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    extra_hosts: Sequence[str] = ()

    async def resolve_verify(
        self,
        author: EventAuthor,
        connection_ids: Sequence[str],
        access_for: AccessFor,
        suffix: str,
        base_url: str | None = None,
    ) -> list[tuple[str, AccessReport]]:
        """Rend (workspace, compte rendu) de chacun ; au premier échec, lève sans rien appliquer.

        `base_url` : nouvelle adresse de la connexion, sous laquelle chaque dépôt doit rester.
        """
        rows = await self.pool.fetch(
            "SELECT id, repo_url, git_connection_id FROM workspaces"
            " WHERE git_connection_id = ANY($1::text[]) AND repo_url IS NOT NULL ORDER BY id",
            list(connection_ids),
        )
        targets = [(r, parse_repository(r["repo_url"], self.extra_hosts)) for r in rows]
        # Tous les dépôts contrôlés avant le premier essai : un refus d'adresse ne doit pas
        # arriver après des écritures déjà faites dans d'autres dépôts.
        for row, repo in targets:
            if base_url is not None and not repository_under(base_url, repo):
                raise DependentOutsideError(row["id"])
        reports = []
        for row, repo in targets:
            access = await access_for(row["git_connection_id"])
            report = await run_access_check(repo, access, suffix)
            # Chaque essai se journalise sur le workspace, réussi ou non : il écrit dans
            # son dépôt (critère 19 de ddfe7a8c).
            async with self.pool.acquire() as conn, conn.transaction():
                await self._event(conn, row["id"], author, check_summary(repo.url, report))
            if not report.all_passed:
                raise DependentCheckFailedError(row["id"], report)
            reports.append((row["id"], report))
        return reports

    @staticmethod
    async def db_store_reports(conn: Any, reports: Sequence[tuple[str, AccessReport]]) -> None:
        """Dans la transaction du changement : le dernier essai affiché est celui qui l'a permis."""
        for workspace_id, report in reports:
            await conn.execute(
                "UPDATE workspaces SET last_check = $2::jsonb, last_check_at = now() WHERE id = $1",
                workspace_id,
                json.dumps(report_json(report)),
            )

    async def _event(
        self, conn: Any, workspace_id: str, author: EventAuthor, properties: dict[str, Any]
    ) -> None:
        event = NewEvent(CHECKED_EVENT, (ObjectRef("workspace", workspace_id),), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)
