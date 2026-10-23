from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.holdspace import HeldCopy
from miles.git.workcopy import BranchMovedError
from miles.workshop.holds_db import Hold, db_hold, db_hold_of, db_holds, db_set_published
from miles.workshop.shelves_db import db_shelf
from miles.workshop.shelving import resume
from miles.workshop.target import Gesture, WorkBranches, base_slug
from miles.workspaces.model import BranchNotFoundError, Workspace, WorkspaceConflictError

log = structlog.get_logger(__name__)

TAKEN_EVENT = "branch_hold.taken"
PUBLISHED_EVENT = "branch_hold.published"
RELEASED_EVENT = "branch_hold.released"
EVENT_TYPES = frozenset({TAKEN_EVENT, PUBLISHED_EVENT, RELEASED_EVENT})


class BranchHeldError(WorkspaceConflictError):
    """La branche est déjà tenue (critère 2) : on nomme qui la tient."""

    def __init__(self, holder: str) -> None:
        super().__init__("branche_tenue")
        self.holder = holder


class AlreadyHoldingError(WorkspaceConflictError):
    """La personne tient déjà une autre branche (critère 3) : on nomme laquelle."""

    def __init__(self, hold: Hold) -> None:
        super().__init__("deja_une_branche")
        self.hold = hold


@dataclass(frozen=True)
class HoldStatus:
    hold: Hold | None
    # Commits locaux non publiés ; None pour qui n'est pas la personne qui a la main.
    unpublished: int | None = None


@dataclass(frozen=True)
class BranchHoldsService:
    """Prise de main d'une branche fille (story 9def0adc, Gael 22/10/2026).

    Une personne par branche, une branche par personne : garanti par les clés d'unicité
    de `branch_holds`, pas par une lecture préalable — deux demandes simultanées ne
    peuvent pas aboutir toutes les deux.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_holds(self, workspace_id: str) -> dict[str, Hold]:
        """Qui tient quelle branche du workspace, par slug."""
        return {h.slug: h for h in await db_holds(self.pool, workspace_id)}

    async def resolve_status(self, person: EventAuthor, workspace_id: str, slug: str) -> HoldStatus:
        await self._child(workspace_id, slug)
        hold = await db_hold(self.pool, workspace_id, slug)
        if hold is None or not hold.held_by(person):
            return HoldStatus(hold)
        workspace = await self.branches.base_workspace(workspace_id)
        async with self.branches.held(workspace, hold) as copy:
            return HoldStatus(hold, await copy.unpublished())

    async def resolve_take(self, person: EventAuthor, workspace_id: str, slug: str) -> Hold:
        """Prend la main ; rejeu par la même personne sur la même branche : sans effet."""
        workspace = await self._child(workspace_id, slug)
        if workspace.git_connection_id is None:
            raise WorkspaceConflictError("depot_non_configure")
        # Vérifié avant d'écrire quoi que ce soit : sans PAT, rien ne se modifierait en son
        # nom, et le refus renvoie au profil (critère 4).
        if (
            await self.branches.identities.resolve_token(person, workspace.git_connection_id)
            is None
        ):
            raise WorkspaceConflictError("identite_git_requise")
        mine = await db_hold_of(self.pool, person)
        if mine is not None:
            if (mine.workspace_id, mine.slug) == (workspace_id, slug):
                return mine
            raise AlreadyHoldingError(mine)
        head = await self._remote_head(person, workspace_id, slug)
        hold = await self._insert(person, workspace_id, slug, workspace.git_connection_id, head)
        try:
            # Une prise neuve part d'un espace neuf : ce qu'un geste tardif aurait laissé
            # sans prise ne doit jamais échoir à la personne suivante.
            await self.branches.holds.discard(workspace_id, slug)
            # Le clone se fait après l'insertion : seul le gagnant clone, avec SON jeton.
            async with self.branches.held(workspace, hold) as copy:
                shelf = await db_shelf(self.pool, workspace_id, slug, person)
                if shelf is not None:
                    # Reprise après déverrouillage (fd1eb7da) : le rangement se fusionne
                    # dans la branche à jour ; un conflit annule la prise.
                    await resume(self.pool, copy, shelf, self.catalog, self.now)
        except Exception:
            # Rien ne doit rester tenu par un espace qui n'a pas pu s'ouvrir.
            await self.pool.execute(
                "DELETE FROM branch_holds WHERE workspace_id = $1 AND slug = $2",
                workspace_id,
                slug,
            )
            await self.branches.holds.discard(workspace_id, slug)
            raise
        await self._event(TAKEN_EVENT, person, hold, {"commit": head})
        log.info("prise_de_main", workspace=workspace_id, branch=slug)
        return hold

    async def resolve_publish(self, person: EventAuthor, workspace_id: str, slug: str) -> int:
        """Pousse les commits locaux avec le PAT de la personne ; rend combien sont partis."""
        hold = await self._mine(person, workspace_id, slug)
        workspace = await self.branches.base_workspace(workspace_id)
        async with self.branches.held(workspace, hold) as copy:
            return await self._publish(copy, person, hold)

    async def resolve_release(self, person: EventAuthor, workspace_id: str, slug: str) -> bool:
        """Publie, libère la branche, supprime l'espace ; rend False au rejeu (sans effet)."""
        hold = await db_hold(self.pool, workspace_id, slug)
        if hold is None or not hold.held_by(person):
            await self._child(workspace_id, slug)
            if hold is None:
                return False
            raise BranchHeldError(hold.holder_label)
        workspace = await self.branches.base_workspace(workspace_id)
        # Publication et libération sous le même verrou d'espace : aucun geste ne peut
        # glisser un commit entre les deux, qui disparaîtrait avec l'espace.
        async with self.branches.held(workspace, hold) as copy:
            # Une publication refusée arrête ici : la main n'est pas rendue sur des
            # commits qui n'existeraient plus nulle part.
            await self._publish(copy, person, hold)
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "DELETE FROM branch_holds WHERE workspace_id = $1 AND slug = $2",
                    workspace_id,
                    slug,
                )
                released = self._new(RELEASED_EVENT, person, hold, {})
                await db_write_event(conn, released, self.catalog, self.now)
        await self.branches.holds.discard(workspace_id, slug)
        log.info("main_rendue", workspace=workspace_id, branch=slug)
        return True

    async def _publish(self, copy: HeldCopy, person: EventAuthor, hold: Hold) -> int:
        count = await copy.unpublished()
        if count == 0:
            return 0
        try:
            head = await copy.publish()
        except BranchMovedError:
            # La branche a bougé dans la forge : rien n'est écrasé, les commits locaux
            # restent dans l'espace (critère 8).
            raise WorkspaceConflictError("branche_modifiee") from None
        await db_set_published(self.pool, hold, head)
        await self._event(PUBLISHED_EVENT, person, hold, {"commit": head, "commits": count})
        log.info("publication", workspace=hold.workspace_id, branch=hold.slug, commits=count)
        return count

    async def _mine(self, person: EventAuthor, workspace_id: str, slug: str) -> Hold:
        await self._child(workspace_id, slug)
        hold = await db_hold(self.pool, workspace_id, slug)
        if hold is None or not hold.held_by(person):
            raise WorkspaceConflictError("prise_de_main_requise")
        return hold

    async def _child(self, workspace_id: str, slug: str) -> Workspace:
        workspace = await self.branches.base_workspace(workspace_id)
        if slug == base_slug(workspace):
            # La racine est en lecture seule (dca0eb0e) : personne n'en prend la main.
            raise WorkspaceConflictError("branche_racine_lecture_seule")
        known = await self.pool.fetchval(
            "SELECT 1 FROM workspace_branches WHERE workspace_id = $1 AND slug = $2",
            workspace_id,
            slug,
        )
        if known is None:
            raise BranchNotFoundError(slug)
        return workspace

    async def _remote_head(self, person: EventAuthor, workspace_id: str, slug: str) -> str:
        # Lue sur la copie partagée, qui suit la forge : c'est la tête publiée du moment.
        async with self.branches.checkout(
            workspace_id, slug, by=person, gesture=Gesture.READ
        ) as copy:
            return copy.head

    async def _insert(
        self, person: EventAuthor, workspace_id: str, slug: str, connection_id: str, head: str
    ) -> Hold:
        try:
            await self.pool.execute(
                "INSERT INTO branch_holds (workspace_id, slug, holder_directory, holder_subject,"
                " connection_id, published_commit, taken_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                workspace_id,
                slug,
                person.directory,
                person.subject,
                connection_id,
                head,
                self.now(),
            )
        except asyncpg.UniqueViolationError:
            # La base a tranché entre deux demandes : on dit qui a gagné, ou ce qu'on tient.
            mine = await db_hold_of(self.pool, person)
            if mine is not None:
                raise AlreadyHoldingError(mine) from None
            other = await db_hold(self.pool, workspace_id, slug)
            if other is None:
                # Tenue puis rendue entre l'insertion refusée et cette relecture : rien de
                # faux à afficher, la personne réessaie.
                raise WorkspaceConflictError("prise_concurrente") from None
            raise BranchHeldError(other.holder_label) from None
        hold = await db_hold(self.pool, workspace_id, slug)
        if hold is None:
            raise WorkspaceConflictError("prise_concurrente")
        return hold

    def _new(self, kind: str, person: EventAuthor, hold: Hold, extra: dict[str, Any]) -> NewEvent:
        properties = {"branch": f"work/{hold.slug}", "slug": hold.slug} | extra
        return NewEvent(kind, (ObjectRef("workspace", hold.workspace_id),), person, properties)

    async def _event(
        self, kind: str, person: EventAuthor, hold: Hold, extra: dict[str, Any]
    ) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, self._new(kind, person, hold, extra), self.catalog, self.now)
