from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.datamodels.grammar import (
    DataModel,
    ModelGrammarError,
    Problem,
    parse_model,
    references_of,
)
from miles.datamodels.layout import (
    ModelEntry,
    checked_name,
    checked_scope,
    entry_of,
    model_path,
    visible_from,
)
from miles.datamodels.meta import meta_path, meta_text, read_label, skeleton
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "data_model.created"
DELETED_EVENT = "data_model.deleted"
REPLACED_EVENT = "data_model.replaced"
EVENT_TYPES = frozenset({CREATED_EVENT, DELETED_EVENT, REPLACED_EVENT})


class ModelNotFoundError(Exception):
    pass


class ModelInUseError(Exception):
    def __init__(self, users: list[str]) -> None:
        super().__init__(f"référencé par {len(users)} modèle(s)")
        self.users = users


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
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[ModelEntry]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return [await _labelled(copy, e) for e in await _entries(copy)]

    async def resolve_get(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str]:
        path = model_path(checked_scope(scope), checked_name(name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(path)
            label = read_label(await copy.read(meta_path(path)))
        if content is None:
            raise ModelNotFoundError(path)
        return ModelEntry(scope, name, path, label), content

    async def resolve_declare(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        label: str,
        slug: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str | None]:
        """Déclare un modèle par son label et son slug (Gael, 23/10/2026).

        Écrit un brouillon sans propriété et son label ; le YAML se complète ensuite à
        l'édition. Rejeu à l'identique : sans effet, commit None.
        """
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        entry = ModelEntry(scope, name, model_path(scope, name), label)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if await copy.read(entry.path) is not None:
                if read_label(await copy.read(meta_path(entry.path))) == label:
                    return entry, None
                raise WorkspaceConflictError("nom_pris")
            await copy.write(entry.path, skeleton(name))
            await copy.write(meta_path(entry.path), meta_text(label))
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_declare", workspace=workspace_id, path=entry.path)
        return entry, commit

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
        scope = checked_scope(scope)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        model = parse_model(content)
        entry = ModelEntry(scope, model.name, model_path(scope, model.name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return entry, None
                raise WorkspaceConflictError("nom_pris")
            await _check_references(copy, scope, model)
            await copy.write(entry.path, content)
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
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
        scope, name = checked_scope(scope), checked_name(name)
        model = parse_model(content)
        if model.name != name:
            raise WorkspaceConflictError("nom_fige")
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await copy.read(entry.path)
            if existing is None:
                raise ModelNotFoundError(entry.path)
            entry = await _labelled(copy, entry)
            if existing == content:
                return entry, None
            await _check_references(copy, scope, model)
            await copy.write(entry.path, content)
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
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
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            entries = await _entries(copy)
            if entry not in entries:
                raise ModelNotFoundError(entry.path)
            users = await _users(copy, entries, entry)
            if users:
                raise ModelInUseError(users)
            await copy.remove(entry.path)
            if await copy.read(meta_path(entry.path)) is not None:
                await copy.remove(meta_path(entry.path))
            commit = await self.branches.commit(copy, f"Suppression du modèle {entry.path}", author)
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


async def _labelled(copy: WorkCopy, entry: ModelEntry) -> ModelEntry:
    label = read_label(await copy.read(meta_path(entry.path)))
    return ModelEntry(entry.scope, entry.name, entry.path, label)


async def _users(copy: WorkCopy, entries: list[ModelEntry], target: ModelEntry) -> list[str]:
    """Modèles qui désignent `target` : sa suppression les casserait (critère 9)."""
    users = []
    for other in entries:
        if other == target or visible_from(entries, other.scope).get(target.name) != target:
            continue
        if target.name in references_of(await copy.read(other.path) or ""):
            users.append(other.path)
    return users
