from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.sources.checks import branch_problems
from miles.sources.layout import (
    SourceDoc,
    SourceProblem,
    form_problems,
    names_in,
    read_source,
    source_path,
    source_text,
)
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceConflictError

log = structlog.get_logger(__name__)

SAVED_EVENT = "data_source.saved"
DELETED_EVENT = "data_source.deleted"
EVENT_TYPES = frozenset({SAVED_EVENT, DELETED_EVENT})


class SourceInvalidError(Exception):
    """Déclaration refusée : tous les écarts, chacun avec le champ qu'il concerne."""

    def __init__(self, problems: list[SourceProblem]) -> None:
        super().__init__(f"{len(problems)} écart(s)")
        self.problems = problems


class SourceNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class Saved:
    doc: SourceDoc
    existed: bool
    # Vrai quand la chaîne ou les propriétés filtrables changent : le prochain import
    # réécrira tous les objets et leur index (critère 17).
    rewrite_announced: bool


@dataclass(frozen=True)
class SourcesService:
    """Sources de données : le référentiel d'objets qu'elles alimentent (story 66391afe).

    Déclarées dans git, homologuées avec le paramétrage. La source désigne sa chaîne de
    transformations par son slug (Gael, 22/10/2026) ; la chaîne s'applique à chaque item.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, workspace_id: str, *, branch: str | None = None
    ) -> list[SourceDoc | str]:
        """Les déclarations lisibles, et le nom seul de celles qui ne le sont pas."""
        async with self.branches.checkout(workspace_id, branch) as copy:
            found: list[SourceDoc | str] = []
            for name in names_in(await copy.paths()):
                doc = read_source(await copy.read(source_path(name)))
                found.append(doc if doc is not None and doc.name == name else name)
            return found

    async def resolve_get(
        self, workspace_id: str, name: str, *, branch: str | None = None
    ) -> SourceDoc:
        async with self.branches.checkout(workspace_id, branch) as copy:
            doc = read_source(await copy.read(source_path(name)))
        if doc is None or doc.name != name:
            raise SourceNotFoundError(name)
        return doc

    async def resolve_save(
        self,
        author: EventAuthor,
        workspace_id: str,
        doc: SourceDoc,
        *,
        create: bool,
        branch: str | None = None,
    ) -> Saved:
        """Déclare (create) ou modifie une source ; tous les écarts sont rendus d'un coup."""
        # Vérifiée avant tout accès au dépôt : une déclaration mal formée ne coûte aucun clone.
        problems = form_problems(doc)
        if problems:
            raise SourceInvalidError(problems)
        async with self.branches.checkout(workspace_id, branch) as copy:
            previous = read_source(await copy.read(source_path(doc.name)))
            if previous is not None and create and previous != doc:
                raise WorkspaceConflictError("nom_pris")
            if previous is None and not create:
                raise SourceNotFoundError(doc.name)
            if previous == doc:
                return Saved(doc, True, False)
            problems = await branch_problems(copy, doc)
            if problems:
                raise SourceInvalidError(problems)
            await copy.write(source_path(doc.name), source_text(doc))
            commit = await self.branches.push(copy, f"Source de données {doc.name}", author)
        rewrite = previous is not None and (
            previous.chain != doc.chain or previous.filterables != doc.filterables
        )
        await self._journal(SAVED_EVENT, workspace_id, author, doc.name, commit, copy.branch)
        log.info("source_enregistree", workspace=workspace_id, source=doc.name, rewrite=rewrite)
        return Saved(doc, False, rewrite)

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> None:
        async with self.branches.checkout(workspace_id, branch) as copy:
            if await copy.read(source_path(name)) is None:
                raise SourceNotFoundError(name)
            # Le refus de supprimer une source qui porte des objets (critère 18) viendra
            # avec l'ingestion (4d4fdcef) : aucun objet n'est encore écrit.
            await copy.remove(source_path(name))
            commit = await self.branches.push(copy, f"Suppression de la source {name}", author)
        await self._journal(DELETED_EVENT, workspace_id, author, name, commit, copy.branch)

    async def _journal(
        self, kind: str, workspace_id: str, author: EventAuthor, name: str, commit: str, branch: str
    ) -> None:
        properties = {"source": name, "commit": commit, "branch": branch}
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
