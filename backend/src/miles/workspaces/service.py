from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.access import GitAccess
from miles.git.forge import Repository, RepositoryUrlError, parse_repository, repository_under
from miles.git.rights import SUFFIX_RE, AccessReport, run_access_check
from miles.git.worktree import (
    BranchExistsError,
    RepositoryAccessError,
    open_work_branch,
    work_branch_name,
)
from miles.gitaccess.model import GitAccessError
from miles.gitaccess.resolver import AccessResolver
from miles.oidc.model import CONNECTOR_ID_RE
from miles.workspaces.model import (
    CHECKED_EVENT,
    CREATED_EVENT,
    NAME_MAX,
    REPOSITORY_EVENT,
    SECURITY_SERVICE_EVENT,
    SELECT,
    WORK_BRANCH_EVENT,
    AccessCheckFailedError,
    RepositoryUnavailableError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
    check_summary,
    commit_author,
    report_json,
    workspace_from_row,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class WorkspacesService:
    """Workspaces : créés par leur nom, puis paramétrés (dépôt, service de sécurité).

    Révision du 21/10/2026 (story 54d6cf1b) : l'accès au dépôt ne vit plus sur le
    workspace mais dans la connexion git qu'il choisit.
    """

    pool: asyncpg.Pool
    resolver: AccessResolver
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Hôtes git admis en plus de GitHub : la forge jetable des tests seulement.
    extra_git_hosts: Sequence[str] = ()

    async def resolve_list(self) -> list[Workspace]:
        rows = await self.pool.fetch(SELECT + " ORDER BY w.name, w.id")
        return [workspace_from_row(r) for r in rows]

    async def resolve_get(self, workspace_id: str) -> Workspace:
        row = await self.pool.fetchrow(SELECT + " WHERE w.id = $1", workspace_id)
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        return workspace_from_row(row)

    async def resolve_create(
        self, author: EventAuthor, workspace_id: str, name: str
    ) -> tuple[Workspace, bool]:
        """Crée le workspace par son nom ; rend (workspace, déjà_là). Rejeu : sans effet."""
        if not CONNECTOR_ID_RE.match(workspace_id):
            raise WorkspaceInputError("id")
        name = name.strip()
        if not name or len(name) > NAME_MAX:
            raise WorkspaceInputError("name")
        existing = await self.pool.fetchrow(SELECT + " WHERE w.id = $1", workspace_id)
        if existing is not None:
            if existing["name"] == name:
                return workspace_from_row(existing), True
            raise WorkspaceConflictError("identifiant_pris")
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO workspaces (id, name, created_at, updated_at)"
                    " VALUES ($1, $2, $3, $3)",
                    workspace_id,
                    name,
                    self.now(),
                )
                await self._event(conn, CREATED_EVENT, workspace_id, author, {"name": name})
        except asyncpg.UniqueViolationError:
            raise WorkspaceConflictError("identifiant_pris") from None
        log.info("workspace_cree", workspace=workspace_id)
        return await self.resolve_get(workspace_id), False

    async def resolve_set_repository(
        self,
        author: EventAuthor,
        workspace_id: str,
        connection_id: str,
        repo_url: str,
        suffix: str,
    ) -> tuple[Workspace, bool]:
        """Associe le dépôt, par une connexion ; rend (workspace, déjà_là).

        Le dépôt n'est enregistré que si les cinq droits passent : le blocage décidé le
        18/10/2026 pour la création s'applique ici depuis le 21/10/2026.
        """
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("verification_suffix")
        workspace = await self.resolve_get(workspace_id)
        repo = self._repository(repo_url)
        if (workspace.repo_url, workspace.git_connection_id) == (repo.url, connection_id):
            return workspace, True
        # Changer le dépôt sous une branche de travail ouverte la laisserait dans l'ancien :
        # non instruit (story 54d6cf1b, « Hors de ce ticket »), donc refusé.
        if workspace.work_branch is not None:
            raise WorkspaceConflictError("branche_de_travail_existante")
        base_url = await self.pool.fetchval(
            "SELECT base_url FROM git_connections WHERE id = $1", connection_id
        )
        if base_url is None:
            raise WorkspaceInputError("git_connection_id")
        if not repository_under(base_url, repo):
            raise WorkspaceInputError("repo_url", "hors_connexion")
        taken = await self.pool.fetchval(
            "SELECT id FROM workspaces WHERE repo_url = $1 AND id <> $2", repo.url, workspace_id
        )
        if taken is not None:
            raise WorkspaceConflictError("depot_deja_associe")
        report = await self._probe(
            author, workspace_id, repo, await self._access(connection_id), suffix
        )
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "UPDATE workspaces SET repo_url = $2, git_connection_id = $3,"
                    " last_check = $4::jsonb, last_check_at = $5, updated_at = $5 WHERE id = $1",
                    workspace_id,
                    repo.url,
                    connection_id,
                    json.dumps(report_json(report)),
                    self.now(),
                )
                properties = {"repo_url": repo.url, "git_connection_id": connection_id}
                await self._event(conn, REPOSITORY_EVENT, workspace_id, author, properties)
        except asyncpg.UniqueViolationError:
            # Même dépôt enregistré en parallèle sur un autre workspace : la base tranche.
            raise WorkspaceConflictError("depot_deja_associe") from None
        log.info("workspace_depot_enregistre", workspace=workspace_id, repo_url=repo.url)
        return await self.resolve_get(workspace_id), False

    async def resolve_set_security_service(
        self, author: EventAuthor, workspace_id: str, service_id: str | None
    ) -> Workspace:
        await self.resolve_get(workspace_id)
        if service_id is not None and not await self.pool.fetchval(
            "SELECT 1 FROM security_services WHERE id = $1", service_id
        ):
            raise WorkspaceInputError("security_service_id")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE workspaces SET security_service_id = $2, updated_at = $3 WHERE id = $1",
                workspace_id,
                service_id,
                self.now(),
            )
            properties = {"security_service_id": service_id}
            await self._event(conn, SECURITY_SERVICE_EVENT, workspace_id, author, properties)
        return await self.resolve_get(workspace_id)

    async def resolve_recheck(
        self, author: EventAuthor, workspace_id: str, suffix: str
    ) -> AccessReport:
        """Rejoue l'essai depuis la fiche : un droit retiré depuis l'enregistrement se voit ici."""
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("verification_suffix")
        workspace, repo, connection_id = await self._configured(workspace_id)
        report = await run_access_check(repo, await self._access(connection_id), suffix)
        async with self.pool.acquire() as conn, conn.transaction():
            await self._store_check(conn, workspace.id, report)
            await self._event(
                conn, CHECKED_EVENT, workspace.id, author, check_summary(repo.url, report)
            )
        return report

    async def resolve_open_work_branch(
        self, author: EventAuthor, workspace_id: str, name: str
    ) -> tuple[Workspace, str | None]:
        """Ouvre LA branche de travail du workspace ; rend (workspace, issue ou None si rejeu).

        Une seule par workspace (choix du 21/10/2026) : la seconde demande, sous le même
        nom, est un rejeu sans effet ; sous un autre nom, un refus.
        """
        try:
            branch = work_branch_name(name)
        except ValueError:
            raise WorkspaceInputError("name") from None
        workspace, repo, connection_id = await self._configured(workspace_id)
        if workspace.work_branch is not None:
            if workspace.work_branch == branch:
                return workspace, None
            raise WorkspaceConflictError("branche_de_travail_existante")
        access = await self._access(connection_id)
        try:
            opened = await open_work_branch(repo, access, name, commit_author(author))
        except RepositoryAccessError as exc:
            raise RepositoryUnavailableError(exc.reason.value) from None
        except BranchExistsError:
            raise WorkspaceConflictError("branche_existante") from None
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO workspace_work_branches (workspace_id, branch, outcome, created_at,"
                " created_by_directory, created_by_subject) VALUES ($1, $2, $3, $4, $5, $6)",
                workspace_id,
                opened.branch,
                opened.outcome,
                self.now(),
                author.directory,
                author.subject,
            )
            properties = {"branch": opened.branch, "outcome": opened.outcome}
            await self._event(conn, WORK_BRANCH_EVENT, workspace_id, author, properties)
        log.info("branche_de_travail_ouverte", workspace=workspace_id, outcome=opened.outcome)
        return await self.resolve_get(workspace_id), opened.outcome

    async def _configured(self, workspace_id: str) -> tuple[Workspace, Repository, str]:
        # Sans dépôt, rien de ce qui touche git n'a de sens : refus nommé plutôt qu'un
        # échec git incompréhensible.
        workspace = await self.resolve_get(workspace_id)
        if workspace.repo_url is None or workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        return workspace, self._repository(workspace.repo_url), workspace.git_connection_id

    def _repository(self, repo_url: str) -> Repository:
        try:
            return parse_repository(repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None

    async def _access(self, connection_id: str) -> GitAccess:
        # L'accès est relu à chaque geste : un PAT ou un certificat remplacé vaut aussitôt.
        try:
            return await self.resolver.for_connection(self.pool, connection_id)
        except GitAccessError:
            raise WorkspaceInputError("git_connection_id") from None

    async def _probe(
        self,
        author: EventAuthor,
        workspace_id: str,
        repo: Repository,
        access: GitAccess,
        suffix: str,
    ) -> AccessReport:
        report = await run_access_check(repo, access, suffix)
        # Chaque essai se journalise, réussi ou non (critère 19) : il écrit dans le dépôt.
        async with self.pool.acquire() as conn, conn.transaction():
            summary = check_summary(repo.url, report)
            await self._event(conn, CHECKED_EVENT, workspace_id, author, summary)
        if not report.all_passed:
            raise AccessCheckFailedError(report)
        return report

    @staticmethod
    async def _store_check(conn: Any, workspace_id: str, report: AccessReport) -> None:
        await conn.execute(
            "UPDATE workspaces SET last_check = $2::jsonb, last_check_at = now() WHERE id = $1",
            workspace_id,
            json.dumps(report_json(report)),
        )

    async def _event(
        self,
        conn: Any,
        event_type: str,
        workspace_id: str,
        author: EventAuthor,
        properties: dict[str, Any],
    ) -> None:
        event = NewEvent(event_type, (ObjectRef("workspace", workspace_id),), author, properties)
        await db_write_event(conn, event, self.catalog, self.now)
