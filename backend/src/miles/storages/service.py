from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.sources.layout import names_in as source_names_in
from miles.sources.layout import read_source, source_path
from miles.storages.checks import branch_problems
from miles.storages.layout import (
    StorageDoc,
    StorageProblem,
    form_problems,
    names_in,
    read_storage,
    storage_path,
    storage_text,
)
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError

log = structlog.get_logger(__name__)

SAVED_EVENT = "storage.saved"
DELETED_EVENT = "storage.deleted"
EVENT_TYPES = frozenset({SAVED_EVENT, DELETED_EVENT})


class StorageInvalidError(Exception):
    """Déclaration refusée : tous les écarts, chacun avec le champ qu'il concerne."""

    def __init__(self, problems: list[StorageProblem]) -> None:
        super().__init__(f"{len(problems)} écart(s)")
        self.problems = problems


class StorageNotFoundError(Exception):
    pass


class StorageInUseError(Exception):
    """Le storage est désigné par des sources : on nomme lesquelles."""

    def __init__(self, sources: list[str]) -> None:
        super().__init__(", ".join(sources))
        self.sources = sources


@dataclass(frozen=True)
class Saved:
    doc: StorageDoc
    existed: bool
    # Vrai quand le modèle ou les propriétés indexables changent : les objets déjà écrits
    # et leur index ne correspondent plus à la déclaration, et le prochain import les
    # réécrira en entier (critère 13).
    rewrite_announced: bool


@dataclass(frozen=True)
class StoragesService:
    """Storages : les collections d'objets JSON de l'application (story 844f15ad).

    Deux notions distinctes de la source de données (Gael, 24/10/2026) : le storage dit
    QUOI est stocké — le modèle, la clé fonctionnelle, les propriétés indexables — et la
    source dit seulement COMMENT on le remplit. Un storage vit sans aucune source.

    Déclaré dans git comme les modèles et les chaînes, pour la même raison : il est
    versionné et homologué avec le reste du paramétrage. Les objets, eux, iront en base.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[StorageDoc | str]:
        """Les déclarations lisibles, et le nom seul de celles qui ne le sont pas."""
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            found: list[StorageDoc | str] = []
            for name in names_in(await copy.paths()):
                doc = read_storage(await copy.read(storage_path(name)))
                found.append(doc if doc is not None and doc.name == name else name)
            return found

    async def resolve_get(
        self, viewer: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> StorageDoc:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            doc = read_storage(await copy.read(storage_path(name)))
        if doc is None or doc.name != name:
            raise StorageNotFoundError(name)
        return doc

    async def resolve_save(
        self,
        author: EventAuthor,
        workspace_id: str,
        doc: StorageDoc,
        *,
        create: bool,
        branch: str | None = None,
    ) -> Saved:
        """Déclare (create) ou modifie un storage ; tous les écarts sont rendus d'un coup."""
        # Vérifiée avant tout accès au dépôt : une déclaration mal formée ne coûte aucun clone.
        problems = form_problems(doc)
        if problems:
            raise StorageInvalidError(problems)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            previous = read_storage(await copy.read(storage_path(doc.name)))
            if previous is not None and create and previous != doc:
                raise WorkspaceConflictError("nom_pris")
            if previous is None and not create:
                raise StorageNotFoundError(doc.name)
            if previous == doc:
                return Saved(doc, True, False)
            problems = await branch_problems(copy, doc)
            if problems:
                raise StorageInvalidError(problems)
            await copy.write(storage_path(doc.name), storage_text(doc))
            commit = await self.branches.commit(copy, f"Storage {doc.name}", author)
        rewrite = previous is not None and (
            previous.model != doc.model or previous.indexables != doc.indexables
        )
        await self._journal(SAVED_EVENT, workspace_id, author, doc.name, commit, copy.branch)
        log.info("storage_enregistre", workspace=workspace_id, storage=doc.name, rewrite=rewrite)
        return Saved(doc, False, rewrite)

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> None:
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await copy.paths()
            if await copy.read(storage_path(name)) is None:
                raise StorageNotFoundError(name)
            # Un storage désigné par une source ne se supprime pas : la source cesserait de
            # se vérifier, et son prochain import échouerait loin de la cause.
            users = [
                source
                for source in source_names_in(paths)
                if (doc := read_source(await copy.read(source_path(source))))
                and doc.storage == name
            ]
            if users:
                raise StorageInUseError(users)
            # Le refus de supprimer un storage qui PORTE des objets (critère 18 de
            # 66391afe) viendra avec l'écriture des objets : aucun n'est encore écrit.
            await copy.remove(storage_path(name))
            commit = await self.branches.commit(copy, f"Suppression du storage {name}", author)
        await self._journal(DELETED_EVENT, workspace_id, author, name, commit, copy.branch)
        log.info("storage_supprime", workspace=workspace_id, storage=name)

    async def _journal(
        self, kind: str, workspace_id: str, author: EventAuthor, name: str, commit: str, branch: str
    ) -> None:
        properties = {"storage": name, "commit": commit, "branch": branch}
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
