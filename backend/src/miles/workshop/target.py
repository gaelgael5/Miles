from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import asyncpg

from miles.events.model import EventAuthor
from miles.git.access import GitAccess
from miles.git.forge import Repository, RepositoryUrlError, parse_repository
from miles.git.workcopy import BranchMissingError, BranchMovedError, WorkCopy
from miles.git.workdirs import WorkDirs
from miles.git.worktree import WORK_BRANCH_PREFIX, RepositoryAccessError
from miles.gitaccess.model import GitAccessError
from miles.gitaccess.resolver import AccessResolver
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceInputError,
    commit_author,
)
from miles.workspaces.service import WorkspacesService


def base_slug(workspace: Workspace) -> str | None:
    if workspace.work_branch is None:
        return None
    return workspace.work_branch.removeprefix(WORK_BRANCH_PREFIX)


@dataclass(frozen=True)
class WorkBranches:
    """Ouvre une branche de travail d'un workspace, et traduit les refus git en refus du workspace.

    Commun à tout ce qui écrit dans l'atelier (modèles, contrats, versions…) : une seule
    règle pour « quelle branche, avec quel accès, et que dire quand le dépôt refuse ».
    """

    pool: asyncpg.Pool
    workspaces: WorkspacesService
    resolver: AccessResolver
    workdirs: WorkDirs
    extra_git_hosts: Sequence[str] = field(default=())

    @asynccontextmanager
    async def checkout(
        self, workspace_id: str, branch: str | None = None, *, edit: bool
    ) -> AsyncIterator[WorkCopy]:
        """`branch` : slug d'une branche du workspace ; None ouvre la base.

        Repli volontaire sur la base : c'est la branche de référence du workspace, et les
        écrans antérieurs aux branches filles (22/10/2026) ne désignent pas de branche.

        `edit` : le geste change-t-il le contenu de la branche ? Sans valeur par défaut,
        exprès : chaque appelant déclare son intention, et un nouveau geste d'écriture ne
        peut pas atteindre la racine par oubli.
        """
        workspace = await self._with_base(workspace_id)
        name = await self._branch_name(workspace, branch)
        if edit and name == workspace.work_branch:
            # La racine est en lecture seule (Gael, 22/10/2026, story dca0eb0e) : on
            # modifie dans une branche enfant. Refusé avant tout clone, et côté serveur,
            # pas seulement par l'écran. Enregistrer une version n'est pas un `edit`.
            raise WorkspaceConflictError("branche_racine_lecture_seule")
        repo, access = await self.repository(workspace)
        try:
            async with self.workdirs.checkout(repo, access, workspace.id, name) as copy:
                yield copy
        except RepositoryAccessError as exc:
            # Dépôt devenu inaccessible : on désigne l'accès, la branche reste intacte.
            raise RepositoryUnavailableError(exc.reason.value) from None
        except BranchMissingError:
            raise WorkspaceConflictError("branche_de_travail_introuvable") from None

    async def base_workspace(self, workspace_id: str) -> Workspace:
        """Le workspace, s'il a un dépôt et une branche de base ; refus nommé sinon."""
        return await self._with_base(workspace_id)

    async def repository(self, workspace: Workspace) -> tuple[Repository, GitAccess]:
        if workspace.repo_url is None or workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        try:
            repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None
        try:
            access = await self.resolver.for_connection(self.pool, workspace.git_connection_id)
        except GitAccessError:
            raise WorkspaceInputError("git_connection_id") from None
        return repo, access

    async def _with_base(self, workspace_id: str) -> Workspace:
        workspace = await self.workspaces.resolve_get(workspace_id)
        if workspace.repo_url is None or workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        # Pas de branche implicite : sans branche de travail, rien à lire ni à écrire.
        if workspace.work_branch is None:
            raise WorkspaceConflictError("branche_de_travail_absente")
        return workspace

    async def _branch_name(self, workspace: Workspace, slug: str | None) -> str:
        base = workspace.work_branch or ""
        if slug is None or slug == base_slug(workspace):
            name = base
        else:
            row = await self.pool.fetchval(
                "SELECT branch FROM workspace_branches WHERE workspace_id = $1 AND slug = $2",
                workspace.id,
                slug,
            )
            if row is None:
                raise BranchNotFoundError(slug)
            name = str(row)
        # L'atelier n'écrit que sur une branche de travail, jamais sur une branche
        # d'environnement : garde redondante avec la création, voulue à ce point d'écriture.
        if not name.startswith(WORK_BRANCH_PREFIX):
            raise WorkspaceConflictError("branche_d_environnement")
        return name

    @staticmethod
    async def push(copy: WorkCopy, message: str, author: EventAuthor) -> str:
        try:
            return await copy.commit_push(message, commit_author(author))
        except BranchMovedError:
            raise WorkspaceConflictError("branche_modifiee") from None
