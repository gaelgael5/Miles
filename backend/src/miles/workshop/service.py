from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.versions import (
    SavedVersion,
    VersionTakenError,
    fetch_versions,
    restore_tree,
    same_tree,
    tag_head,
)
from miles.workshop.target import WorkBranches
from miles.workshop.validation import FileReport, validate_branch
from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError, commit_author

log = structlog.get_logger(__name__)

SAVED_EVENT = "work_version.saved"
RESTORED_EVENT = "work_version.restored"
EVENT_TYPES = frozenset({SAVED_EVENT, RESTORED_EVENT})
LABEL_MAX = 200


class InvalidConfigurationError(Exception):
    """Le paramétrage ne passe pas les règles : on ne fige pas un état incohérent."""

    def __init__(self, reports: list[FileReport]) -> None:
        super().__init__(f"{len(reports)} fichier(s) en défaut")
        self.reports = reports


class VersionNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class WorkshopService:
    """Enregistrement explicite d'une version sur la branche de travail (story 94b06105).

    Jamais automatique : la cohérence de l'état figé vient de l'intention de quelqu'un,
    pas de la mécanique. Aucun merge vers une branche d'environnement : reporté par Gael.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self, workspace_id: str) -> list[SavedVersion]:
        async with self.branches.checkout(workspace_id) as copy:
            return await fetch_versions(copy)

    async def resolve_save(
        self, author: EventAuthor, workspace_id: str, label: str
    ) -> tuple[SavedVersion, bool]:
        """Fige la tête de la branche ; rend (version, déjà_là). Rejeu : sans effet."""
        label = _label(label)
        identity = commit_author(author)
        async with self.branches.checkout(workspace_id) as copy:
            versions = await fetch_versions(copy)
            last = versions[0] if versions else None
            if last is not None and await same_tree(copy, last.commit):
                if last.commit == copy.head and last.label == label:
                    return last, True
                raise WorkspaceConflictError("rien_a_figer")
            reports = await validate_branch(copy)
            if reports:
                raise InvalidConfigurationError(reports)
            number = last.number + 1 if last is not None else 1
            try:
                # La version fige la tête lue au départ, et la réponse dit laquelle : une
                # écriture arrivée entre-temps n'y entre pas (critère 6).
                await tag_head(copy, number, label, identity)
            except VersionTakenError:
                raise WorkspaceConflictError("version_concurrente") from None
            saved = SavedVersion(number, label, copy.head, identity, self.now())
        await self._event(workspace_id, SAVED_EVENT, author, _summary(saved))
        log.info("version_enregistree", workspace=workspace_id, version=number)
        return saved, False

    async def resolve_restore(self, author: EventAuthor, workspace_id: str, number: int) -> str:
        """Revient à une version par un NOUVEAU commit : l'historique n'est pas réécrit."""
        async with self.branches.checkout(workspace_id) as copy:
            versions = {v.number: v for v in await fetch_versions(copy)}
            version = versions.get(number)
            if version is None:
                raise VersionNotFoundError(number)
            if await same_tree(copy, version.commit):
                raise WorkspaceConflictError("deja_a_cette_version")
            await restore_tree(copy, version.commit)
            message = f"Retour à la version {number} — {version.label}"
            commit = await self.branches.push(copy, message, author)
        properties = _summary(version) | {"restored_commit": commit}
        await self._event(workspace_id, RESTORED_EVENT, author, properties)
        log.info("version_restauree", workspace=workspace_id, version=number)
        return commit

    async def _event(
        self, workspace_id: str, event_type: str, author: EventAuthor, properties: dict[str, Any]
    ) -> None:
        event = NewEvent(event_type, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _summary(version: SavedVersion) -> dict[str, Any]:
    return {"version": version.number, "commit": version.commit, "label": version.label}


def _label(label: str) -> str:
    # Une version sans libellé est inutilisable six mois plus tard, au moment précis où
    # on en a besoin (critère 5). Une ligne : il devient le sujet de l'étiquette.
    label = label.strip()
    if not label or len(label) > LABEL_MAX or "\n" in label:
        raise WorkspaceInputError("label")
    return label
