from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.datamodels.grammar import (
    NAME_RE,
    DataModel,
    ModelGrammarError,
    Problem,
    parse_model,
    references_of,
)
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError

log = structlog.get_logger(__name__)

SHARED = "shared"
CREATED_EVENT = "data_model.created"
DELETED_EVENT = "data_model.deleted"
REPLACED_EVENT = "data_model.replaced"
EVENT_TYPES = frozenset({CREATED_EVENT, DELETED_EVENT, REPLACED_EVENT})
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
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, workspace_id: str, *, branch: str | None = None
    ) -> list[ModelEntry]:
        async with self.branches.checkout(workspace_id, branch, edit=False) as copy:
            return await _entries(copy)

    async def resolve_get(
        self, workspace_id: str, scope: str, name: str, *, branch: str | None = None
    ) -> tuple[ModelEntry, str]:
        path = model_path(_scope(scope), _name(name))
        async with self.branches.checkout(workspace_id, branch, edit=False) as copy:
            content = await copy.read(path)
        if content is None:
            raise ModelNotFoundError(path)
        return ModelEntry(scope, name, path), content

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str | None]:
        """Écrit un modèle ; rend (modèle, commit). Rejeu du même contenu : sans effet, None."""
        scope = _scope(scope)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        model = parse_model(content)
        entry = ModelEntry(scope, model.name, model_path(scope, model.name))
        async with self.branches.checkout(workspace_id, branch, edit=True) as copy:
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return entry, None
                raise WorkspaceConflictError("nom_pris")
            await _check_references(copy, scope, model)
            await copy.write(entry.path, content)
            commit = await self.branches.push(copy, f"Modèle de données {entry.path}", author)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_cree", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def resolve_replace(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str | None]:
        """Remplace un modèle existant ; rend (modèle, commit). Même contenu : sans effet, None.

        Le nom ne change pas par un remplacement : les modèles qui le désignent par son nom
        resteraient sans cible. Renommer, c'est créer l'autre et supprimer celui-ci.
        """
        scope, name = _scope(scope), _name(name)
        model = parse_model(content)
        if model.name != name:
            raise WorkspaceConflictError("nom_fige")
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(workspace_id, branch, edit=True) as copy:
            existing = await copy.read(entry.path)
            if existing is None:
                raise ModelNotFoundError(entry.path)
            if existing == content:
                return entry, None
            await _check_references(copy, scope, model)
            await copy.write(entry.path, content)
            commit = await self.branches.push(copy, f"Modèle de données {entry.path}", author)
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_remplace", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def resolve_delete(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> str:
        scope, name = _scope(scope), _name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(workspace_id, branch, edit=True) as copy:
            entries = await _entries(copy)
            if entry not in entries:
                raise ModelNotFoundError(entry.path)
            users = await _users(copy, entries, entry)
            if users:
                raise ModelInUseError(users)
            await copy.remove(entry.path)
            commit = await self.branches.push(copy, f"Suppression du modèle {entry.path}", author)
        await self._event(workspace_id, DELETED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_supprime", workspace=workspace_id, path=entry.path)
        return commit

    async def _event(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        entry: ModelEntry,
        commit: str,
        branch: str,
    ) -> None:
        # Après le push : le journal dit ce qui est dans git. Le contenu n'y va pas, le
        # chemin et le commit suffisent à le retrouver.
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"path": entry.path, "commit": commit, "branch": branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def _check_references(copy: WorkCopy, scope: str, model: DataModel) -> None:
    visible = visible_from(await _entries(copy), scope)
    missing = [
        Problem(path, "modele_inconnu", target)
        for path, target in model.references
        if target not in visible and target != model.name
    ]
    if missing:
        raise ModelGrammarError(missing)


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
