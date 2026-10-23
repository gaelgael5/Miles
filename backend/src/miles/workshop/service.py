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
from miles.git.versions import (
    SavedVersion,
    VersionTakenError,
    fetch_versions,
    restore_tree,
    same_tree,
    tag_head,
)
from miles.git.workcopy import WorkCopy
from miles.workshop.target import Gesture, WorkBranches
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

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[SavedVersion]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            mine, _ = await self._branch_versions(workspace_id, copy)
            return mine

    async def resolve_save(
        self, author: EventAuthor, workspace_id: str, label: str, *, branch: str | None = None
    ) -> tuple[SavedVersion, bool]:
        """Fige la tête de la branche ; rend (version, déjà_là). Rejeu : sans effet."""
        label = _label(label)
        # Pas une modification : une étiquette fige la branche sans en changer le contenu,
        # et reste permise sur la racine (Gael, 22/10/2026). Sur une branche fille, elle
        # suppose la main et une tête publiée (9def0adc, critère 11).
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.FREEZE
        ) as copy:
            mine, last_number = await self._branch_versions(workspace_id, copy)
            last = mine[0] if mine else None
            if last is not None and await same_tree(copy, last.commit):
                if last.commit == copy.head and last.label == label:
                    return last, True
                raise WorkspaceConflictError("rien_a_figer")
            # Sur une branche tenue, l'étiqueteur est la personne telle que la forge la
            # connaît, comme l'auteur de ses commits ; sur la racine, l'auteur de Miles.
            identity = copy.signature if isinstance(copy, HeldCopy) else commit_author(author)
            reports = await validate_branch(copy)
            if reports:
                raise InvalidConfigurationError(reports)
            # Numéro unique au dépôt (Gael, 22/10/2026) : un numéro désigne un seul état,
            # quelle que soit la branche, et c'est lui qu'on déploiera.
            number = last_number + 1
            try:
                # La version fige la tête lue au départ, et la réponse dit laquelle : une
                # écriture arrivée entre-temps n'y entre pas (critère 6).
                await tag_head(copy, number, label, identity)
            except VersionTakenError:
                raise WorkspaceConflictError("version_concurrente") from None
            saved = SavedVersion(number, label, copy.head, identity, self.now(), copy.branch)
        await self._event(workspace_id, SAVED_EVENT, author, _summary(saved, copy.branch))
        log.info("version_enregistree", workspace=workspace_id, version=number)
        return saved, False

    async def resolve_restore(
        self, author: EventAuthor, workspace_id: str, number: int, *, branch: str | None = None
    ) -> str:
        """Revient à une version par un NOUVEAU commit : l'historique n'est pas réécrit."""
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            # Seulement les versions de cette branche : ses modifications lui sont propres,
            # y ramener l'état d'une autre branche serait une fusion déguisée.
            mine, _ = await self._branch_versions(workspace_id, copy)
            versions = {v.number: v for v in mine}
            version = versions.get(number)
            if version is None:
                raise VersionNotFoundError(number)
            if await same_tree(copy, version.commit):
                raise WorkspaceConflictError("deja_a_cette_version")
            await restore_tree(copy, version.commit)
            message = f"Retour à la version {number} — {version.label}"
            commit = await self.branches.commit(copy, message, author)
        properties = _summary(version, copy.branch) | {"restored_commit": commit}
        await self._event(workspace_id, RESTORED_EVENT, author, properties)
        log.info("version_restauree", workspace=workspace_id, version=number)
        return commit

    async def _branch_versions(
        self, workspace_id: str, copy: WorkCopy
    ) -> tuple[list[SavedVersion], int]:
        """Versions de la branche de la copie, et le dernier numéro pris dans tout le dépôt."""
        every = await fetch_versions(copy)
        base = (await self.branches.base_workspace(workspace_id)).work_branch
        # Une étiquette sans branche date d'avant les branches filles : elle est à la base.
        mine = [v for v in every if (v.branch or base) == copy.branch]
        return mine, every[0].number if every else 0

    async def _event(
        self, workspace_id: str, event_type: str, author: EventAuthor, properties: dict[str, Any]
    ) -> None:
        event = NewEvent(event_type, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _summary(version: SavedVersion, branch: str) -> dict[str, Any]:
    return {
        "version": version.number,
        "commit": version.commit,
        "label": version.label,
        "branch": branch,
    }


def _label(label: str) -> str:
    # Une version sans libellé est inutilisable six mois plus tard, au moment précis où
    # on en a besoin (critère 5). Une ligne : il devient le sujet de l'étiquette.
    label = label.strip()
    if not label or len(label) > LABEL_MAX or "\n" in label:
        raise WorkspaceInputError("label")
    return label
