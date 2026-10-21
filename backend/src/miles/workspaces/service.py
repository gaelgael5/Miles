from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.forge import Repository, RepositoryUrlError, parse_repository
from miles.git.rights import SUFFIX_RE, AccessReport, run_access_check
from miles.git.worktree import (
    BranchExistsError,
    RepositoryAccessError,
    open_work_branch,
    work_branch_name,
)
from miles.oidc.model import CONNECTOR_ID_RE
from miles.secrets.model import Consumer, Secret, SecretError
from miles.secrets.service import SecretsService, resolve_attach_secret

log = structlog.get_logger(__name__)

CREATED_EVENT = "workspace.created"
CHECKED_EVENT = "workspace.access_checked"
WORK_BRANCH_EVENT = "workspace.work_branch_opened"
EVENT_TYPES = frozenset({CREATED_EVENT, CHECKED_EVENT, WORK_BRANCH_EVENT})
GIT_SECRET_TYPE = "GIT_TOKEN"  # noqa: S105  # nom du type, pas une valeur
_NAME_MAX = 200
_SELECT = (
    "SELECT w.id, w.name, w.repo_url, w.git_secret_slug, w.security_service_id, w.last_check,"
    " w.last_check_at, w.created_at, w.updated_at, b.branch AS work_branch FROM workspaces w"
    " LEFT JOIN workspace_work_branches b ON b.workspace_id = w.id"
)
_COMMIT_IDENTITY_RE = re.compile(r"[^A-Za-z0-9._-]")


class WorkspaceError(Exception):
    """Refus ; le message ne porte jamais de secret."""


class WorkspaceInputError(WorkspaceError):
    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class WorkspaceConflictError(WorkspaceError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkspaceNotFoundError(WorkspaceError):
    pass


class RepositoryUnavailableError(WorkspaceError):
    """Le dépôt a cessé de répondre ou de nous laisser faire : on désigne l'accès (critère 10)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccessCheckFailedError(WorkspaceError):
    """Un des cinq droits manque : le workspace n'est pas créé (décision du 18/10/2026)."""

    def __init__(self, report: AccessReport) -> None:
        super().__init__("accès au dépôt insuffisant")
        self.report = report


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    repo_url: str
    git_secret_slug: str
    security_service_id: str | None
    last_check: dict[str, Any] | None
    last_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Aucune à la création : elle s'ouvre quand on commence à travailler (critère 2).
    work_branch: str | None = None


@dataclass(frozen=True)
class WorkspaceInput:
    id: str
    name: str
    repo_url: str
    git_secret_slug: str | None
    security_service_id: str | None


def report_json(report: AccessReport) -> dict[str, Any]:
    return asdict(report) | {"all_passed": report.all_passed}


def _workspace(row: Any) -> Workspace:
    data = dict(row)
    raw = data["last_check"]
    data["last_check"] = json.loads(raw) if isinstance(raw, str) else raw
    return Workspace(**data)


@dataclass(frozen=True)
class WorkspacesService:
    pool: asyncpg.Pool
    secrets: SecretsService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Hôtes git admis en plus de GitHub : vide en production, la forge jetable en test.
    extra_git_hosts: Sequence[str] = ()

    async def resolve_list(self) -> list[Workspace]:
        return [_workspace(r) for r in await self.pool.fetch(_SELECT + " ORDER BY w.name, w.id")]

    async def resolve_get(self, workspace_id: str) -> Workspace:
        row = await self.pool.fetchrow(_SELECT + " WHERE w.id = $1", workspace_id)
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        return _workspace(row)

    async def resolve_create(
        self, author: EventAuthor, data: WorkspaceInput, suffix: str
    ) -> tuple[Workspace, bool]:
        """Crée le workspace après avoir éprouvé les cinq droits ; rend (workspace, déjà_là).

        Rejeu à l'identique : sans effet, et signalé (critère 16).
        """
        repo, name, secret_slug = self._validate(data, suffix)
        existing = await self.pool.fetchrow(_SELECT + " WHERE w.id = $1", data.id)
        if existing is not None:
            if existing["repo_url"] == repo.url:
                return _workspace(existing), True
            raise WorkspaceConflictError("identifiant_pris")
        if await self.pool.fetchval("SELECT 1 FROM workspaces WHERE repo_url = $1", repo.url):
            raise WorkspaceConflictError("depot_deja_associe")
        token = await self._check_references(data, secret_slug)
        report = await run_access_check(repo, token, suffix)
        await self._journal_check(author, data.id, repo.url, report)
        if not report.all_passed:
            raise AccessCheckFailedError(report)
        now = self.now()
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await resolve_attach_secret(
                    conn, secret_slug, GIT_SECRET_TYPE, Consumer("workspace", data.id)
                )
                await conn.execute(
                    "INSERT INTO workspaces (id, name, repo_url, git_secret_slug,"
                    " security_service_id, last_check, last_check_at, created_at, updated_at)"
                    " VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $7, $7)",
                    data.id,
                    name,
                    repo.url,
                    secret_slug,
                    data.security_service_id,
                    json.dumps(report_json(report)),
                    now,
                )
                await self._event(
                    conn, CREATED_EVENT, data.id, author, {"repo_url": repo.url, "name": name}
                )
        except asyncpg.UniqueViolationError:
            # Création concurrente du même identifiant ou du même dépôt : la base tranche.
            raise WorkspaceConflictError("identifiant_ou_depot_pris") from None
        log.info("workspace_cree", workspace=data.id, repo_url=repo.url)
        return await self.resolve_get(data.id), False

    async def resolve_recheck(
        self, author: EventAuthor, workspace_id: str, suffix: str
    ) -> AccessReport:
        """Rejoue l'essai depuis la fiche : un droit retiré depuis la création se voit ici."""
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("suffix")
        workspace = await self.resolve_get(workspace_id)
        repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        try:
            token = await self.secrets.resolve_secret(workspace.git_secret_slug, GIT_SECRET_TYPE)
        except SecretError:
            raise WorkspaceInputError("git_secret_slug") from None
        report = await run_access_check(repo, token, suffix)
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE workspaces SET last_check = $2::jsonb, last_check_at = $3 WHERE id = $1",
                workspace_id,
                json.dumps(report_json(report)),
                self.now(),
            )
            await self._event(
                conn, CHECKED_EVENT, workspace_id, author, _check_summary(repo.url, report)
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
        workspace = await self.resolve_get(workspace_id)
        if workspace.work_branch is not None:
            if workspace.work_branch == branch:
                return workspace, None
            raise WorkspaceConflictError("branche_de_travail_existante")
        repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        try:
            token = await self.secrets.resolve_secret(workspace.git_secret_slug, GIT_SECRET_TYPE)
            opened = await open_work_branch(repo, token, name, _commit_author(author))
        except SecretError:
            raise WorkspaceInputError("git_secret_slug") from None
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

    def _validate(self, data: WorkspaceInput, suffix: str) -> tuple[Repository, str, str]:
        if not CONNECTOR_ID_RE.match(data.id):
            raise WorkspaceInputError("id")
        name = data.name.strip()
        if not name or len(name) > _NAME_MAX:
            raise WorkspaceInputError("name")
        try:
            repo = parse_repository(data.repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None
        # Ni secret ni certificat : refus avant toute tentative (critère 2). Le certificat
        # arrive avec le ticket 63ecbec8 ; ici, le jeton est le seul moyen d'accès.
        if not data.git_secret_slug:
            raise WorkspaceInputError("git_secret_slug")
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("suffix")
        return repo, name, data.git_secret_slug

    async def _check_references(self, data: WorkspaceInput, secret_slug: str) -> Secret:
        if data.security_service_id is not None and not await self.pool.fetchval(
            "SELECT 1 FROM security_services WHERE id = $1", data.security_service_id
        ):
            raise WorkspaceInputError("security_service_id")
        try:
            return await self.secrets.resolve_secret(secret_slug, GIT_SECRET_TYPE)
        except SecretError:
            raise WorkspaceInputError("git_secret_slug") from None

    async def _journal_check(
        self, author: EventAuthor, workspace_id: str, repo_url: str, report: AccessReport
    ) -> None:
        # Chaque essai se journalise, réussi ou non (critère 19) : il écrit dans le dépôt.
        async with self.pool.acquire() as conn, conn.transaction():
            await self._event(
                conn, CHECKED_EVENT, workspace_id, author, _check_summary(repo_url, report)
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


def _commit_author(author: EventAuthor) -> str:
    """Auteur du commit d'initialisation : la personne, et par où elle est entrée (critère 11)."""
    subject = _COMMIT_IDENTITY_RE.sub("-", author.subject)[:60] or "inconnu"
    directory = _COMMIT_IDENTITY_RE.sub("-", author.directory)[:60] or "inconnu"
    return f"{subject} via Miles <{subject}@{directory}.miles.invalid>"


def _check_summary(repo_url: str, report: AccessReport) -> dict[str, Any]:
    return {
        "repo_url": repo_url,
        "branch": report.branch,
        "all_passed": report.all_passed,
        "checks": {c.right.value: c.reason.value if c.reason else "ok" for c in report.checks},
        "residual_branch": report.residual_branch,
        "residual_tag": report.residual_tag,
    }
