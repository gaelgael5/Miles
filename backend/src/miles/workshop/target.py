from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

import asyncpg

from miles.events.model import DelegatedAuthor, EventAuthor
from miles.git.access import GitAccess
from miles.git.forge import Repository, RepositoryUrlError, parse_repository
from miles.git.holdspace import HeldCopy, HoldSpaces
from miles.git.workcopy import BranchMissingError, WorkCopy
from miles.git.workdirs import WorkDirs
from miles.git.worktree import WORK_BRANCH_PREFIX, RepositoryAccessError
from miles.gitaccess.model import GitAccessError
from miles.gitaccess.resolver import AccessResolver
from miles.identities.service import GitIdentitiesService
from miles.workshop.holds_db import Hold, db_hold, db_set_published
from miles.workspaces.model import (
    BranchNotFoundError,
    HoldRequiredError,
    RepositoryUnavailableError,
    Workspace,
    WorkspaceConflictError,
    WorkspaceInputError,
    git_signature,
)
from miles.workspaces.service import WorkspacesService


def base_slug(workspace: Workspace) -> str | None:
    if workspace.work_branch is None:
        return None
    return workspace.work_branch.removeprefix(WORK_BRANCH_PREFIX)


class Gesture(Enum):
    """Ce que fait un geste sur une branche ; chaque appelant le déclare (dca0eb0e, 9def0adc)."""

    # Lire : ouvert à tous ; la personne qui a la main lit ses commits non publiés.
    READ = "read"
    # Changer le contenu : jamais la racine, et seulement par qui a la main.
    EDIT = "edit"
    # Figer une version : permis sur la racine (Gael, 22/10/2026) ; sur une branche fille,
    # par qui a la main et sans commit local non publié (critère 11).
    FREEZE = "freeze"


@dataclass(frozen=True)
class WorkBranches:
    """Ouvre une branche de travail d'un workspace, et traduit les refus git en refus du workspace.

    Commun à tout ce qui lit ou écrit dans l'atelier (modèles, contrats, versions…) : une
    seule règle pour « quelle branche, quelle copie, avec quel accès, et que dire quand le
    dépôt refuse ».
    """

    pool: asyncpg.Pool
    workspaces: WorkspacesService
    resolver: AccessResolver
    workdirs: WorkDirs
    holds: HoldSpaces
    identities: GitIdentitiesService
    extra_git_hosts: Sequence[str] = field(default=())

    @asynccontextmanager
    async def checkout(
        self,
        workspace_id: str,
        branch: str | None = None,
        *,
        by: EventAuthor,
        gesture: Gesture,
    ) -> AsyncIterator[WorkCopy]:
        """`branch` : slug d'une branche du workspace ; None ouvre la base.

        Repli volontaire sur la base : c'est la branche de référence du workspace, et les
        écrans antérieurs aux branches filles (22/10/2026) ne désignent pas de branche.

        `by` et `gesture` sans valeur par défaut, exprès : chaque appelant dit qui agit et
        ce qu'il fait, et un nouveau geste d'écriture ne peut contourner ni la racine en
        lecture seule ni la prise de main par oubli.
        """
        workspace = await self._with_base(workspace_id)
        name = await self._branch_name(workspace, branch)
        if name == workspace.work_branch:
            if gesture is Gesture.EDIT:
                # La racine est en lecture seule (Gael, 22/10/2026, story dca0eb0e) : on
                # modifie dans une branche enfant. Refusé avant tout clone, côté serveur.
                raise WorkspaceConflictError("branche_racine_lecture_seule")
            async with self._shared(workspace, name) as copy:
                yield copy
            return
        hold = await db_hold(self.pool, workspace.id, name.removeprefix(WORK_BRANCH_PREFIX))
        mine = hold is not None and hold.held_by(by)
        if gesture is not Gesture.READ and not mine:
            # Sans la main, rien ne se modifie (Gael, 22/10/2026) : vaut pour l'écran comme
            # pour MCP, et c'est ici, au seul point d'ouverture, que ça se garantit.
            raise HoldRequiredError(None if hold is None else hold.holder_label)
        if hold is None or not mine:
            # Les autres lisent ce qui est publié : un commit local n'est visible que de
            # qui l'a fait, jusqu'à sa publication (voulu, ticket 9def0adc).
            async with self._shared(workspace, name) as copy:
                yield copy
            return
        async with self.held(workspace, hold) as held:
            if gesture is Gesture.FREEZE and await held.unpublished():
                # Une version fige la tête publiée, celle que tout le monde voit dans la
                # forge (Gael, 22/10/2026) : un commit local n'y entrerait pas.
                raise WorkspaceConflictError("publication_requise")
            yield held

    @asynccontextmanager
    async def held(self, workspace: Workspace, hold: Hold) -> AsyncIterator[HeldCopy]:
        """L'espace de la personne qui a la main, ouvert avec SON jeton, jamais celui du service.

        Interdit par le ticket : écrire sur une branche tenue avec le PAT du workspace.
        """
        repo, _ = await self.repository(workspace)
        token = await self.identities.resolve_token(hold.holder, hold.connection_id)
        signature = await self.identities.resolve_signature(hold.holder, hold.connection_id)
        if token is None or signature is None:
            # Inatteignable tant que le retrait du PAT est refusé pendant la prise
            # (critère 12) : fermé quand même, sans repli sur le jeton du service.
            raise WorkspaceConflictError("identite_git_requise")
        try:
            async with self.holds.open(
                repo,
                GitAccess(token),
                workspace.id,
                hold.slug,
                published=hold.published_commit,
                signature=git_signature(*signature),
            ) as copy:
                # Relue sous le verrou de l'espace : une prise rendue ou déverrouillée
                # pendant qu'un geste attendait ne lui laisse rien écrire.
                current = await db_hold(self.pool, workspace.id, hold.slug)
                if current is None or current.taken_at != hold.taken_at:
                    raise HoldRequiredError(None if current is None else current.holder_label)
                if copy.published != hold.published_commit:
                    # L'espace s'est recalé sur la forge : c'est la nouvelle tête publiée,
                    # le bail de la prochaine publication.
                    await db_set_published(self.pool, hold, copy.published)
                yield copy
        except RepositoryAccessError as exc:
            raise RepositoryUnavailableError(exc.reason.value) from None
        except BranchMissingError:
            raise WorkspaceConflictError("branche_de_travail_introuvable") from None

    @asynccontextmanager
    async def _shared(self, workspace: Workspace, name: str) -> AsyncIterator[WorkCopy]:
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
    async def commit(copy: WorkCopy, message: str, author: EventAuthor) -> str:
        """Commit LOCAL dans l'espace de qui a la main ; « Publier » le poussera (9def0adc)."""
        if not isinstance(copy, HeldCopy):
            # Toute modification passe par `checkout(gesture=EDIT)`, qui n'ouvre que
            # l'espace de la personne : une copie partagée ici est une faute de programme.
            raise TypeError("une modification se commite dans l'espace de prise de main")
        if isinstance(author, DelegatedAuthor):
            # « Les deux » (Gael, 22/10/2026) : l'auteur est la personne, le message dit
            # par quelle clé l'agent a écrit — seule trace git de qui a demandé quoi.
            channel = "la clé d'API" if author.via_kind == "api_key" else "le client OAuth"
            message = f"{message}\n\nVia {channel} « {author.via_key_label} »."
        return await copy.commit_local(message)
