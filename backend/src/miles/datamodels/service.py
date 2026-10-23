from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.datamodels.grammar import ModelGrammarError, Problem
from miles.datamodels.layout import (
    ModelEntry,
    checked_name,
    checked_scope,
    entry_of,
    model_path,
    visible,
)
from miles.datamodels.meta import meta_path, meta_text, read_version
from miles.datamodels.schema import (
    ModelSchema,
    draft,
    normalized,
    parse_schema,
    references_in,
)
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

    Des JSON Schema 2020-12 en YAML depuis le 23/10/2026 (story 0f7cda10).

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
            return [await _described(copy, e) for e in await _entries(copy)]

    async def resolve_get(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str]:
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise ModelNotFoundError(entry.path)
            return await _described(copy, entry), content

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

        Écrit un schéma objet sans propriété, le label en `title`, et la version 1 ; le
        schéma se complète ensuite à l'édition. Rejeu à l'identique : sans effet, None.
        """
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        content = draft(scope, name, label)
        return await self._create(author, workspace_id, scope, name, content, branch)

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str | None]:
        """Écrit un modèle depuis son schéma ; rejeu du même schéma : sans effet, None."""
        scope, name = checked_scope(scope), checked_name(name)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        parse_schema(content)
        return await self._create(
            author, workspace_id, scope, name, normalized(content, scope, name), branch
        )

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
        """Remplace le schéma d'un modèle ; même schéma : sans effet, None.

        Le nom ne change pas : c'est le fichier et l'`$id`, que le système réécrit. La
        version monte de 1, tenue par le système (Gael, 23/10/2026).
        """
        scope, name = checked_scope(scope), checked_name(name)
        schema = parse_schema(content)
        content = normalized(content, scope, name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await copy.read(entry.path)
            if existing is None:
                raise ModelNotFoundError(entry.path)
            if existing == content:
                return await _described(copy, entry), None
            await _check_references(copy, entry, schema)
            version = read_version(await copy.read(meta_path(entry.path))) + 1
            await copy.write(entry.path, content)
            await copy.write(meta_path(entry.path), meta_text(version))
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
            entry = await _described(copy, entry)
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_remplace", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def _create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        branch: str | None,
    ) -> tuple[ModelEntry, str | None]:
        schema = parse_schema(content)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return await _described(copy, entry), None
                raise WorkspaceConflictError("nom_pris")
            await _check_references(copy, entry, schema)
            await copy.write(entry.path, content)
            # Un modèle naît en version 1 : la version est au système, jamais au client.
            await copy.write(meta_path(entry.path), meta_text(1))
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
            entry = await _described(copy, entry)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_cree", workspace=workspace_id, path=entry.path)
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


async def _check_references(copy: WorkCopy, entry: ModelEntry, schema: ModelSchema) -> None:
    known = {(e.scope, e.name) for e in await _entries(copy)} | {(entry.scope, entry.name)}
    missing = [
        Problem(where, "modele_inconnu", f"{scope}/{name}")
        for where, (scope, name) in schema.references
        if (scope, name) not in known or not visible(entry, (scope, name))
    ]
    if missing:
        raise ModelGrammarError(missing)


async def _entries(copy: WorkCopy) -> list[ModelEntry]:
    return [e for e in map(entry_of, await copy.paths()) if e is not None]


async def _described(copy: WorkCopy, entry: ModelEntry) -> ModelEntry:
    """Le modèle avec son label (le `title` du schéma) et sa version (ses métadonnées)."""
    text = await copy.read(entry.path)
    try:
        label = parse_schema(text or "").title
    except ValueError:
        # Illisible (retouché hors de Miles) : listé quand même, sans label ; la
        # validation de la branche dira pourquoi.
        label = None
    version = read_version(await copy.read(meta_path(entry.path)))
    return ModelEntry(entry.scope, entry.name, entry.path, label, version or None)


async def _users(copy: WorkCopy, entries: list[ModelEntry], target: ModelEntry) -> list[str]:
    """Modèles qui désignent `target` : sa suppression les casserait."""
    users = []
    for other in entries:
        if other == target:
            continue
        if (target.scope, target.name) in references_in(await copy.read(other.path) or ""):
            users.append(other.path)
    return users
