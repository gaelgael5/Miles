from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.workshop.target import Gesture, WorkBranches
from miles.workshop.trads import file_missing_keys
from miles.workspaces.cultures import (
    CULTURE_ADDED_EVENT,
    CULTURE_REMOVED_EVENT,
    DEFAULT_CULTURE_EVENT,
    DefaultCultureIncompleteError,
    WorkspaceCultures,
    checked_culture,
    db_add_culture,
    db_cultures,
    db_remove_culture,
    db_switch_default,
)
from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError

log = structlog.get_logger(__name__)

# Refus de `checkout` qui veulent dire « il n'y a rien à lire », et non « la lecture a
# échoué » : ce sont les deux états normaux d'un workspace qu'on vient de créer.
_NOTHING_TO_READ = frozenset({"depot_non_configure", "branche_de_travail_absente"})


@dataclass(frozen=True)
class WorkspaceCulturesService:
    """Les langues du paramétrage d'un workspace (story 639c25da).

    Distinctes des cultures actives de l'application, qui sont les langues de l'OUTIL :
    traduire un paramétrage en thaï n'exige pas de lire le back-office en thaï. Le
    référentiel de traductions lit CELLES-CI.
    """

    pool: asyncpg.Pool
    # Pour compter, dans le dépôt, ce qui manque avant d'accepter un changement de culture
    # par défaut : le référentiel vit dans git, pas en base.
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_cultures(self, workspace_id: str) -> WorkspaceCultures:
        return await db_cultures(self.pool, workspace_id)

    async def resolve_add(
        self, author: EventAuthor, workspace_id: str, culture: str
    ) -> WorkspaceCultures:
        """Ajoute une culture additionnelle. Rejeu, ou culture par défaut : sans effet."""
        culture = checked_culture(culture)
        async with self.pool.acquire() as conn, conn.transaction():
            added = await _add(conn, workspace_id, culture)
            if added:
                await self._event(conn, CULTURE_ADDED_EVENT, workspace_id, author, culture)
        if added:
            log.info("workspace_culture_ajoutee", workspace=workspace_id, culture=culture)
        return await self.resolve_cultures(workspace_id)

    async def resolve_remove(
        self, author: EventAuthor, workspace_id: str, culture: str
    ) -> WorkspaceCultures:
        """Retire une culture additionnelle. Ses fichiers restent dans le dépôt (critère 7).

        Rien n'est supprimé dans git, exprès : on ne détruit pas un travail de traduction
        en décochant une case, et c'est ce qui fait réapparaître les valeurs telles quelles
        si la culture est remise (critère 8). Même règle que pour une culture désactivée
        dans l'application.
        """
        culture = checked_culture(culture)
        async with self.pool.acquire() as conn, conn.transaction():
            removed = await db_remove_culture(conn, workspace_id, culture)
            if removed:
                await self._event(conn, CULTURE_REMOVED_EVENT, workspace_id, author, culture)
        if removed:
            log.info("workspace_culture_retiree", workspace=workspace_id, culture=culture)
        return await self.resolve_cultures(workspace_id)

    async def resolve_set_default(
        self, author: EventAuthor, workspace_id: str, culture: str
    ) -> WorkspaceCultures:
        """Change la culture par défaut, refusé tant que des clés manquent dedans (critère 6)."""
        culture = checked_culture(culture)
        current = await db_cultures(self.pool, workspace_id)
        if current.default == culture:
            return current
        missing = await self._missing(author, workspace_id, culture)
        if missing:
            raise DefaultCultureIncompleteError(culture, missing)
        async with self.pool.acquire() as conn, conn.transaction():
            # Une culture jamais ajoutée au workspace peut être visée : elle entre d'abord
            # comme additionnelle, pour que la validation contre le catalogue reste au même
            # endroit, puis se promeut.
            await _add(conn, workspace_id, culture)
            await db_switch_default(conn, workspace_id, culture)
            await self._event(
                conn,
                DEFAULT_CULTURE_EVENT,
                workspace_id,
                author,
                culture,
                {"previous": current.default},
            )
        log.info("workspace_culture_defaut", workspace=workspace_id, culture=culture)
        return await self.resolve_cultures(workspace_id)

    async def _missing(self, viewer: EventAuthor, workspace_id: str, culture: str) -> int:
        """Clés sans valeur dans cette culture, sur la BRANCHE DE BASE du workspace.

        La base, et non toutes les branches : le réglage est au workspace comme elle, et
        une branche de travail en cours est normalement incomplète — exiger qu'elles le
        soient toutes rendrait le changement impossible à obtenir, pour un refus que
        personne ne saurait lever.
        """
        try:
            async with self.branches.checkout(
                workspace_id, None, by=viewer, gesture=Gesture.READ
            ) as copy:
                return await file_missing_keys(copy.read, await copy.paths(), culture)
        except WorkspaceConflictError as exc:
            if exc.code not in _NOTHING_TO_READ:
                raise
            # Repli volontaire : un workspace sans dépôt ou sans branche n'a aucune
            # traduction, donc rien ne manque. Laisser remonter ces deux refus ferait
            # répondre « dépôt non configuré » à qui choisit une langue, ce qui ne
            # désigne pas la cause et bloquerait un réglage légitime.
            return 0

    async def _event(
        self,
        conn: Any,
        event_type: str,
        workspace_id: str,
        author: EventAuthor,
        culture: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"culture": culture} | (extra or {}),
        )
        await db_write_event(conn, event, self.catalog, self.now)


async def _add(conn: Any, workspace_id: str, culture: str) -> bool:
    """Ajoute, en traduisant le refus de la base : la culture doit être au catalogue.

    La clé étrangère vers `cultures` est la garde — on insère et on laisse la base
    trancher, plutôt que de relire le catalogue, ce qui laisserait passer deux appels
    concurrents entre la lecture et l'écriture.
    """
    try:
        return await db_add_culture(conn, workspace_id, culture)
    except asyncpg.ForeignKeyViolationError:
        raise WorkspaceInputError("culture", "inconnue") from None
