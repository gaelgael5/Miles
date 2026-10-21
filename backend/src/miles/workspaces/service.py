from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.access import GitAccess
from miles.git.forge import Repository, RepositoryUrlError, parse_repository
from miles.git.rights import SUFFIX_RE, AccessReport, run_access_check
from miles.git.worktree import (
    BranchExistsError,
    RepositoryAccessError,
    open_work_branch,
    work_branch_name,
)
from miles.oidc.model import CONNECTOR_ID_RE
from miles.secrets.model import Consumer
from miles.secrets.service import SecretsService, resolve_attach_secret, resolve_detach_secret
from miles.workspaces.access import CLIENT_KEY_TYPE, TOKEN_TYPE, AccessResolver
from miles.workspaces.model import (
    CERTIFICATE_EVENT,
    CHECKED_EVENT,
    CREATED_EVENT,
    NAME_MAX,
    SELECT,
    WORK_BRANCH_EVENT,
    AccessCheckFailedError,
    CertificateInput,
    RepositoryUnavailableError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceInput,
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
    pool: asyncpg.Pool
    secrets: SecretsService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Hôtes git admis en plus de GitHub, et autorité de confiance : la forge jetable des
    # tests seulement, vides en production.
    extra_git_hosts: Sequence[str] = ()
    git_ca_file: Path | None = None
    access: AccessResolver = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "access", AccessResolver(self.secrets, self.now, self.git_ca_file))

    async def resolve_list(self) -> list[Workspace]:
        rows = await self.pool.fetch(SELECT + " ORDER BY w.name, w.id")
        return [workspace_from_row(r) for r in rows]

    async def resolve_get(self, workspace_id: str) -> Workspace:
        row = await self.pool.fetchrow(SELECT + " WHERE w.id = $1", workspace_id)
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        return workspace_from_row(row)

    async def resolve_create(
        self, author: EventAuthor, data: WorkspaceInput, suffix: str
    ) -> tuple[Workspace, bool]:
        """Crée le workspace après avoir éprouvé les cinq droits ; rend (workspace, déjà_là).

        Rejeu à l'identique : sans effet, et signalé (critère 16).
        """
        repo, name = self._validate(data, suffix)
        existing = await self.pool.fetchrow(SELECT + " WHERE w.id = $1", data.id)
        if existing is not None:
            if existing["repo_url"] == repo.url:
                return workspace_from_row(existing), True
            raise WorkspaceConflictError("identifiant_pris")
        if await self.pool.fetchval("SELECT 1 FROM workspaces WHERE repo_url = $1", repo.url):
            raise WorkspaceConflictError("depot_deja_associe")
        await self._check_security_service(data.security_service_id)
        access, not_after = await self.access.resolve(data.git_secret_slug, data.certificate)
        report = await self._probe(author, data.id, repo, access, suffix)
        cert = data.certificate
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await self._attach(conn, data.id, data.git_secret_slug, cert)
                await conn.execute(
                    "INSERT INTO workspaces (id, name, repo_url, git_secret_slug,"
                    " client_cert_pem, client_key_secret_slug, client_cert_not_after,"
                    " security_service_id, last_check, last_check_at, created_at, updated_at)"
                    " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $10, $10)",
                    data.id,
                    name,
                    repo.url,
                    data.git_secret_slug or None,
                    cert.cert_pem if cert else None,
                    cert.key_secret_slug if cert else None,
                    not_after,
                    data.security_service_id,
                    json.dumps(report_json(report)),
                    self.now(),
                )
                properties = {"repo_url": repo.url, "name": name, "client_certificate": bool(cert)}
                await self._event(conn, CREATED_EVENT, data.id, author, properties)
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
        access = await self.access.resolve_for(workspace)
        report = await run_access_check(repo, access, suffix)
        async with self.pool.acquire() as conn, conn.transaction():
            await self._store_check(conn, workspace_id, report)
            await self._event(
                conn, CHECKED_EVENT, workspace_id, author, check_summary(repo.url, report)
            )
        return report

    async def resolve_replace_certificate(
        self, author: EventAuthor, workspace_id: str, certificate: CertificateInput, suffix: str
    ) -> Workspace:
        """Remplace le certificat client sans recréer le workspace, après l'avoir éprouvé.

        Le nouveau certificat ne remplace l'ancien que si les cinq droits passent avec lui :
        sinon on couperait l'accès au dépôt d'un workspace qui fonctionnait.
        """
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("suffix")
        workspace = await self.resolve_get(workspace_id)
        repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        access, not_after = await self.access.resolve(workspace.git_secret_slug, certificate)
        report = await self._probe(author, workspace_id, repo, access, suffix)
        async with self.pool.acquire() as conn, conn.transaction():
            consumer = Consumer("workspace", workspace_id)
            if workspace.client_key_secret_slug:
                await resolve_detach_secret(conn, workspace.client_key_secret_slug, consumer)
            await resolve_attach_secret(
                conn, certificate.key_secret_slug, CLIENT_KEY_TYPE, consumer
            )
            await conn.execute(
                "UPDATE workspaces SET client_cert_pem = $2, client_key_secret_slug = $3,"
                " client_cert_not_after = $4, updated_at = $5 WHERE id = $1",
                workspace_id,
                certificate.cert_pem,
                certificate.key_secret_slug,
                not_after,
                self.now(),
            )
            await self._store_check(conn, workspace_id, report)
            properties = {"not_after": not_after.isoformat() if not_after else None}
            await self._event(conn, CERTIFICATE_EVENT, workspace_id, author, properties)
        log.info("certificat_client_remplace", workspace=workspace_id)
        return await self.resolve_get(workspace_id)

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
        access = await self.access.resolve_for(workspace)
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

    def _validate(self, data: WorkspaceInput, suffix: str) -> tuple[Repository, str]:
        if not CONNECTOR_ID_RE.match(data.id):
            raise WorkspaceInputError("id")
        name = data.name.strip()
        if not name or len(name) > NAME_MAX:
            raise WorkspaceInputError("name")
        try:
            repo = parse_repository(data.repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None
        if not SUFFIX_RE.match(suffix):
            raise WorkspaceInputError("suffix")
        return repo, name

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

    async def _check_security_service(self, service_id: str | None) -> None:
        if service_id is not None and not await self.pool.fetchval(
            "SELECT 1 FROM security_services WHERE id = $1", service_id
        ):
            raise WorkspaceInputError("security_service_id")

    @staticmethod
    async def _attach(
        conn: Any, workspace_id: str, token_slug: str | None, cert: CertificateInput | None
    ) -> None:
        # Les secrets d'un workspace sont des secrets de l'instance qu'il référence
        # (choix du 21/10/2026) : le socle refuse de supprimer un secret encore référencé.
        consumer = Consumer("workspace", workspace_id)
        if token_slug:
            await resolve_attach_secret(conn, token_slug, TOKEN_TYPE, consumer)
        if cert is not None:
            await resolve_attach_secret(conn, cert.key_secret_slug, CLIENT_KEY_TYPE, consumer)

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
