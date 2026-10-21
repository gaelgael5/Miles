from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import structlog

from miles.datamodels.grammar import (
    NAME_RE,
    ModelGrammarError,
    Problem,
    parse_model,
    references_of,
)
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.forge import Repository, RepositoryUrlError, parse_repository
from miles.git.workcopy import BranchMissingError, BranchMovedError, WorkCopy, checkout
from miles.git.worktree import RepositoryAccessError
from miles.gitaccess.model import GitAccessError
from miles.gitaccess.resolver import AccessResolver
from miles.workspaces.model import (
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    commit_author,
)
from miles.workspaces.service import WorkspacesService

log = structlog.get_logger(__name__)

SHARED = "shared"
CREATED_EVENT = "data_model.created"
DELETED_EVENT = "data_model.deleted"
EVENT_TYPES = frozenset({CREATED_EVENT, DELETED_EVENT})
# Emplacements retenus au cadrage : un modèle transverse sous shared/, un modèle de
# domaine sous domains/<domaine>/. Aucun dossier d'environnement : l'environnement est
# une branche. On ne promeut au transverse qu'au second usage réel.
_PATH_RE = re.compile(
    r"^(?:shared/messages/(?P<shared>[^/]+)|domains/(?P<domain>[^/]+)/messages/(?P<name>[^/]+))"
    r"\.yaml$"
)


@dataclass(frozen=True)
class ModelEntry:
    scope: str  # « shared », ou le nom du domaine
    name: str
    path: str


class ModelNotFoundError(Exception):
    pass


class ModelInUseError(Exception):
    def __init__(self, users: list[str]) -> None:
        super().__init__(f"référencé par {len(users)} modèle(s)")
        self.users = users


def model_path(scope: str, name: str) -> str:
    if scope == SHARED:
        return f"shared/messages/{name}.yaml"
    return f"domains/{scope}/messages/{name}.yaml"


def entry_of(path: str) -> ModelEntry | None:
    match = _PATH_RE.match(path)
    if match is None:
        return None
    if match["shared"] is not None:
        return ModelEntry(SHARED, match["shared"], path)
    return ModelEntry(match["domain"], match["name"], path)


def visible_from(entries: Sequence[ModelEntry], scope: str) -> dict[str, ModelEntry]:
    """Modèles qu'un document de `scope` peut désigner, par nom.

    Un modèle de domaine voit ceux de son domaine puis les transverses, le sien masquant
    un transverse de même nom ; un transverse ne voit que les transverses — il ne peut
    pas dépendre d'un domaine sans cesser d'être transverse.
    """
    visible = {e.name: e for e in entries if e.scope == SHARED}
    if scope != SHARED:
        visible |= {e.name: e for e in entries if e.scope == scope}
    return visible


@dataclass(frozen=True)
class DataModelsService:
    """Modèles de données du workspace, écrits dans SA branche de travail (story 266f5ed8).

    Jamais en base, même en cache : le catalogue doit refléter exactement la version git.
    """

    pool: asyncpg.Pool
    workspaces: WorkspacesService
    resolver: AccessResolver
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    extra_git_hosts: Sequence[str] = field(default=())

    async def resolve_list(self, workspace_id: str) -> list[ModelEntry]:
        async with self._copy(workspace_id) as copy:
            return await _entries(copy)

    async def resolve_get(self, workspace_id: str, scope: str, name: str) -> tuple[ModelEntry, str]:
        path = model_path(_scope(scope), _name(name))
        async with self._copy(workspace_id) as copy:
            content = await copy.read(path)
        if content is None:
            raise ModelNotFoundError(path)
        return ModelEntry(scope, name, path), content

    async def resolve_create(
        self, author: EventAuthor, workspace_id: str, scope: str, content: str
    ) -> tuple[ModelEntry, bool]:
        """Écrit un modèle ; rend (modèle, déjà_là). Rejeu du même contenu : sans effet."""
        scope = _scope(scope)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        model = parse_model(content)
        entry = ModelEntry(scope, model.name, model_path(scope, model.name))
        async with self._copy(workspace_id) as copy:
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return entry, True
                raise WorkspaceConflictError("nom_pris")
            visible = visible_from(await _entries(copy), scope)
            missing = [
                Problem(path, "modele_inconnu", target)
                for path, target in model.references
                if target not in visible and target != model.name
            ]
            if missing:
                raise ModelGrammarError(missing)
            await copy.write(entry.path, content)
            commit = await self._push(copy, f"Modèle de données {entry.path}", author)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit)
        log.info("modele_de_donnees_cree", workspace=workspace_id, path=entry.path)
        return entry, False

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, scope: str, name: str
    ) -> None:
        scope, name = _scope(scope), _name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self._copy(workspace_id) as copy:
            entries = await _entries(copy)
            if entry not in entries:
                raise ModelNotFoundError(entry.path)
            users = await _users(copy, entries, entry)
            if users:
                raise ModelInUseError(users)
            await copy.remove(entry.path)
            commit = await self._push(copy, f"Suppression du modèle {entry.path}", author)
        await self._event(workspace_id, DELETED_EVENT, author, entry, commit)
        log.info("modele_de_donnees_supprime", workspace=workspace_id, path=entry.path)

    @asynccontextmanager
    async def _copy(self, workspace_id: str) -> AsyncIterator[WorkCopy]:
        """Copie de la branche de travail, refus git traduits en refus du workspace."""
        repo, connection_id, branch = await self._target(workspace_id)
        try:
            access = await self.resolver.for_connection(self.pool, connection_id)
        except GitAccessError:
            raise WorkspaceInputError("git_connection_id") from None
        try:
            async with checkout(repo, access, branch) as copy:
                yield copy
        except RepositoryAccessError as exc:
            # Dépôt devenu inaccessible : on désigne l'accès, la branche reste intacte.
            raise RepositoryUnavailableError(exc.reason.value) from None
        except BranchMissingError:
            raise WorkspaceConflictError("branche_de_travail_introuvable") from None

    async def _target(self, workspace_id: str) -> tuple[Repository, str, str]:
        workspace = await self.workspaces.resolve_get(workspace_id)
        if workspace.repo_url is None or workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        # Pas de branche implicite (critère 10) : sans branche de travail, rien à écrire.
        if workspace.work_branch is None:
            raise WorkspaceConflictError("branche_de_travail_absente")
        try:
            repo = parse_repository(workspace.repo_url, self.extra_git_hosts)
        except RepositoryUrlError:
            raise WorkspaceInputError("repo_url") from None
        return repo, workspace.git_connection_id, workspace.work_branch

    async def _push(self, copy: WorkCopy, message: str, author: EventAuthor) -> str:
        try:
            return await copy.commit_push(message, commit_author(author))
        except BranchMovedError:
            raise WorkspaceConflictError("branche_modifiee") from None

    async def _event(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        entry: ModelEntry,
        commit: str,
    ) -> None:
        # Après le push : le journal dit ce qui est dans git. Le contenu n'y va pas, le
        # chemin et le commit suffisent à le retrouver.
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"path": entry.path, "commit": commit},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def _entries(copy: WorkCopy) -> list[ModelEntry]:
    return [e for e in map(entry_of, await copy.paths()) if e is not None]


async def _users(copy: WorkCopy, entries: list[ModelEntry], target: ModelEntry) -> list[str]:
    """Modèles qui désignent `target` : sa suppression les casserait (critère 9)."""
    users = []
    for other in entries:
        if other == target or visible_from(entries, other.scope).get(target.name) != target:
            continue
        if target.name in references_of(await copy.read(other.path) or ""):
            users.append(other.path)
    return users


def _scope(scope: str) -> str:
    if scope != SHARED and not NAME_RE.match(scope):
        raise WorkspaceInputError("scope")
    return scope


def _name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name
