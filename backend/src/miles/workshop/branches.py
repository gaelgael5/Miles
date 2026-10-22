from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.rights import classify
from miles.git.workcopy import WorkCopy
from miles.git.worktree import WORK_BRANCH_PREFIX, WORK_NAME_RE
from miles.workshop.target import WorkBranches, base_slug
from miles.workspaces.model import (
    RepositoryUnavailableError,
    WorkspaceInputError,
    checked_label,
)

log = structlog.get_logger(__name__)

CREATED_EVENT = "workspace.branch_created"
EVENT_TYPES = frozenset({CREATED_EVENT})


@dataclass(frozen=True)
class BranchEntry:
    slug: str
    label: str
    branch: str
    # La branche de travail de base du workspace, d'où les autres se tirent.
    base: bool


class BranchTakenError(Exception):
    """Slug ou branche git déjà occupés : on nomme l'occupant."""

    def __init__(self, occupant: str) -> None:
        super().__init__(f"branche occupée par {occupant}")
        self.occupant = occupant


@dataclass(frozen=True)
class BranchesService:
    """Branches de travail filles d'un workspace (story 6a74c474, Gael 22/10/2026).

    Une branche fille se tire de la tête de la base : on y prépare ses modifications sans
    toucher la base. La fusion vers la base n'est pas ici (story 88ed70f1).
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self, workspace_id: str) -> list[BranchEntry]:
        workspace = await self.branches.base_workspace(workspace_id)
        base = base_slug(workspace) or ""
        rows = await self.pool.fetch(
            "SELECT slug, label, branch FROM workspace_branches WHERE workspace_id = $1"
            " ORDER BY created_at, slug",
            workspace_id,
        )
        # La base n'a pas de label saisi : elle s'est ouverte par son seul nom.
        entries = [BranchEntry(base, base, workspace.work_branch or "", True)]
        return entries + [BranchEntry(r["slug"], r["label"], r["branch"], False) for r in rows]

    async def resolve_create(
        self, author: EventAuthor, workspace_id: str, label: str, slug: str
    ) -> tuple[BranchEntry, bool]:
        """Crée la branche fille ; rend (branche, déjà_là). Rejeu à l'identique : sans effet."""
        label, slug = checked_label(label), _slug(slug)
        entry = BranchEntry(slug, label, WORK_BRANCH_PREFIX + slug, False)
        for existing in await self.resolve_list(workspace_id):
            if existing.slug == slug:
                if existing == entry:
                    return existing, True
                raise BranchTakenError(existing.label)
        async with self.branches.checkout(workspace_id) as copy:
            await _push_new_branch(copy, entry.branch)
            base_commit = copy.head
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO workspace_branches (workspace_id, slug, label, branch, base_commit,"
                " created_at, created_by_directory, created_by_subject)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                workspace_id,
                slug,
                label,
                entry.branch,
                base_commit,
                self.now(),
                author.directory,
                author.subject,
            )
            properties = {"slug": slug, "branch": entry.branch, "base_commit": base_commit}
            event = NewEvent(
                CREATED_EVENT, (ObjectRef("workspace", workspace_id),), author, properties
            )
            await db_write_event(conn, event, self.catalog, self.now)
        log.info("branche_fille_creee", workspace=workspace_id, branch=entry.branch)
        return entry, False


async def _push_new_branch(copy: WorkCopy, branch: str) -> None:
    """Pose `branch` sur la tête de la copie, sans commit : un simple pointeur sur la base."""
    ref = f"refs/heads/{branch}"
    # Vérifiée à part : une branche déjà posée sur la tête de la base rend le push « à
    # jour » sans que git consulte le bail, et la création réussirait à tort.
    listed = await copy.git("ls-remote", "--heads", copy.repo.url, ref)
    if not listed.ok:
        raise RepositoryUnavailableError(classify(listed).value)
    if listed.stdout.strip():
        raise BranchTakenError(branch)
    # Bail vide : la branche ne doit pas exister. Un simple push avancerait une branche
    # existante dont la tête serait un ancêtre de la base, au lieu de refuser.
    pushed = await copy.git(
        "push", "-q", f"--force-with-lease={ref}:", copy.repo.url, f"{copy.head}:{ref}"
    )
    if not pushed.ok:
        if "stale info" in pushed.stderr or "rejected" in pushed.stderr:
            raise BranchTakenError(branch)
        raise RepositoryUnavailableError(classify(pushed).value)


def _slug(slug: str) -> str:
    slug = slug.strip()
    if not slug:
        raise WorkspaceInputError("slug", "vide")
    # Même format que la base (`work/<nom>`) : le slug est le nom de la branche git.
    if not WORK_NAME_RE.match(slug):
        raise WorkspaceInputError("slug")
    return slug
