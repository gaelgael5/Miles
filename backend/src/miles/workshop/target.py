from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import asyncpg

from miles.events.model import EventAuthor
from miles.git.forge import RepositoryUrlError, parse_repository
from miles.git.workcopy import BranchMissingError, BranchMovedError, WorkCopy, checkout
from miles.git.worktree import WORK_BRANCH_PREFIX, RepositoryAccessError
from miles.gitaccess.model import GitAccessError
from miles.gitaccess.resolver import AccessResolver
from miles.workspaces.model import (
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    commit_author,
)
from miles.workspaces.service import WorkspacesService


@dataclass(frozen=True)
class WorkBranches:
    """Ouvre LA branche de travail d'un workspace, et traduit les refus git en refus du workspace.

    Commun à tout ce qui écrit dans l'atelier (modèles, versions…) : une seule règle
    pour « quelle branche, avec quel accès, et que dire quand le dépôt refuse ».
    """

    pool: asyncpg.Pool
    workspaces: WorkspacesService
    resolver: AccessResolver
    extra_git_hosts: Sequence[str] = field(default=())

    @asynccontextmanager
    async def checkout(self, workspace_id: str) -> AsyncIterator[WorkCopy]:
        workspace = await self.workspaces.resolve_get(workspace_id)
        if workspace.repo_url is None or workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        # Pas de branche implicite : sans branche de travail, rien à lire ni à écrire.
        if workspace.work_branch is None:
            raise WorkspaceConflictError("branche_de_travail_absente")
        # L'atelier n'écrit que sur une branche de travail, jamais sur une branche
        # d'environnement : garde redondante avec l'ouverture, voulue à ce point d'écriture.
        if not workspace.work_branch.startswith(WORK_BRANCH_PREFIX):
            raise WorkspaceConflictError("branche_d_environnement")
        try:
            repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None
        try:
            access = await self.resolver.for_connection(self.pool, workspace.git_connection_id)
        except GitAccessError:
            raise WorkspaceInputError("git_connection_id") from None
        try:
            async with checkout(repo, access, workspace.work_branch) as copy:
                yield copy
        except RepositoryAccessError as exc:
            # Dépôt devenu inaccessible : on désigne l'accès, la branche reste intacte.
            raise RepositoryUnavailableError(exc.reason.value) from None
        except BranchMissingError:
            raise WorkspaceConflictError("branche_de_travail_introuvable") from None

    @staticmethod
    async def push(copy: WorkCopy, message: str, author: EventAuthor) -> str:
        try:
            return await copy.commit_push(message, commit_author(author))
        except BranchMovedError:
            raise WorkspaceConflictError("branche_modifiee") from None
