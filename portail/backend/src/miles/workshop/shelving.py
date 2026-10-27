from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.holdspace import HeldCopy
from miles.git.shelf import ShelfMissingError, ShelfTakenError, drop_shelf, merge_shelf, shelve
from miles.workshop.holds_db import Hold, db_hold
from miles.workshop.shelves_db import (
    Shelf,
    db_delete_shelf,
    db_insert_shelf,
    db_shelf,
    db_shelves,
    db_shelves_of,
)
from miles.workshop.target import WorkBranches
from miles.workspaces.model import RepositoryUnavailableError, WorkspaceConflictError

log = structlog.get_logger(__name__)

UNLOCKED_EVENT = "branch_hold.unlocked"
RESUMED_EVENT = "branch_hold.resumed"
EVENT_TYPES = frozenset({UNLOCKED_EVENT, RESUMED_EVENT})
# Un login de forge tel que GitHub les admet : il devient un segment de nom de branche.
_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


class ShelfConflictError(WorkspaceConflictError):
    """La reprise heurte la branche à jour (critère 7) : on nomme les fichiers."""

    def __init__(self, files: list[str]) -> None:
        super().__init__("conflit_de_reprise")
        self.files = files


def shelf_name(login: str | None, slug: str) -> str:
    if login is None or not _LOGIN_RE.match(login):
        # Sans login lisible, pas de nom de rangement sûr : refus plutôt qu'un nom deviné.
        raise WorkspaceConflictError("identite_git_requise")
    return f"shelve/{login}/{slug}"


async def resume(
    pool: asyncpg.Pool,
    copy: HeldCopy,
    shelf: Shelf,
    catalog: EventTypeCatalog,
    now: Callable[[], datetime],
) -> None:
    """Fusionne le rangement dans l'espace qu'on vient d'ouvrir, puis le retire de la forge."""
    try:
        tip, conflicts = await merge_shelf(copy, shelf.shelf_branch)
    except ShelfMissingError:
        # Repli voulu : un rangement supprimé dans GitHub l'a été par un geste explicite
        # sur la forge. Le garder en base bloquerait la personne à chaque reprise.
        log.warning("rangement_absent", workspace=shelf.workspace_id, branch=shelf.slug)
        await db_delete_shelf(pool, shelf)
        return
    if conflicts:
        raise ShelfConflictError(conflicts)
    await drop_shelf(copy, shelf.shelf_branch, tip)
    properties = {"slug": shelf.slug, "shelf": shelf.shelf_branch, "commit": tip}
    event = NewEvent(
        RESUMED_EVENT, (ObjectRef("workspace", shelf.workspace_id),), shelf.holder, properties
    )
    async with pool.acquire() as conn, conn.transaction():
        await db_delete_shelf(conn, shelf)
        await db_write_event(conn, event, catalog, now)
    log.info("rangement_repris", workspace=shelf.workspace_id, branch=shelf.slug)


@dataclass(frozen=True)
class ShelvesService:
    """Déverrouiller une personne, et ce qu'elle a de rangé (story fd1eb7da, Gael 22/10/2026)."""

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self, workspace_id: str) -> list[Shelf]:
        return await db_shelves(self.pool, workspace_id)

    async def resolve_mine(self, person: EventAuthor) -> list[Shelf]:
        return await db_shelves_of(self.pool, person)

    async def resolve_unlock(
        self, admin: EventAuthor, workspace_id: str, slug: str
    ) -> Shelf | None:
        """Range le travail non publié de qui tient la branche, puis la libère.

        Rend le rangement, ou None s'il n'y avait rien à ranger (critère 4). Rien n'est
        supprimé tant que le rangement n'est pas relu sur la forge (critère 3).
        """
        hold = await db_hold(self.pool, workspace_id, slug)
        if hold is None:
            raise WorkspaceConflictError("branche_libre")
        workspace = await self.branches.base_workspace(workspace_id)
        shelf: Shelf | None = None
        try:
            async with self.branches.held(workspace, hold) as copy:
                if await copy.unpublished():
                    shelf = await self._shelve(copy, workspace.name, hold)
                # Libéré sous le verrou de l'espace : aucun geste ne peut glisser un commit
                # entre le rangement et la libération, qui disparaîtrait avec l'espace.
                await self._release(admin, hold.holder, workspace_id, slug, shelf)
        except RepositoryUnavailableError as exc:
            if exc.reason == "identifiants":
                # PAT de la personne expiré ou révoqué : refus, la branche reste tenue
                # (Gael, 22/10/2026). Aucun repli sur le jeton du service.
                raise WorkspaceConflictError("jeton_personnel_refuse") from None
            raise
        # Seulement maintenant : le rangement est relu sur la forge et inscrit en base.
        await self.branches.holds.discard(workspace_id, slug)
        log.info("deverrouillage", workspace=workspace_id, branch=slug, range=shelf is not None)
        return shelf

    async def _shelve(self, copy: HeldCopy, workspace_name: str, hold: Hold) -> Shelf:
        name = shelf_name(hold.holder_login, hold.slug)
        if await db_shelf(self.pool, hold.workspace_id, hold.slug, hold.holder) is not None:
            raise WorkspaceConflictError("rangement_existant")
        try:
            commit = await shelve(copy, name)
        except ShelfTakenError:
            raise WorkspaceConflictError("rangement_existant") from None
        return Shelf(
            hold.workspace_id,
            workspace_name,
            hold.slug,
            hold.holder,
            hold.connection_id,
            name,
            commit,
            self.now(),
        )

    async def _release(
        self,
        admin: EventAuthor,
        holder: EventAuthor,
        workspace_id: str,
        slug: str,
        shelf: Shelf | None,
    ) -> None:
        properties = {
            "slug": slug,
            "holder_directory": holder.directory,
            "holder_subject": holder.subject,
            "shelf": None if shelf is None else shelf.shelf_branch,
            "commit": None if shelf is None else shelf.shelved_commit,
        }
        event = NewEvent(UNLOCKED_EVENT, (ObjectRef("workspace", workspace_id),), admin, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            if shelf is not None:
                await db_insert_shelf(conn, shelf, admin)
            await conn.execute(
                "DELETE FROM branch_holds WHERE workspace_id = $1 AND slug = $2",
                workspace_id,
                slug,
            )
            await db_write_event(conn, event, self.catalog, self.now)
