from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.git.versions import SavedVersion

from miles.git.holdspace import HeldCopy
from miles.git.versions import VersionTakenError, fetch_versions, restore_tree, same_tree, tag_head
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
class FreezeBlock:
    """Ce qui empêche d'enregistrer une version ici, et le DÉTAIL quand c'est le paramétrage.

    Les rapports sont rendus AVEC la raison, et pas à sa place : « publiez d'abord » et
    « ces trois fichiers ne passent pas les règles » sont deux choses, et celui qui
    publiera veut savoir tout de suite que le figement échouera ensuite. C'est la demande
    de Gael du 01/11/2026 — « il faudrait que le message d'erreur arrive avant que j'aie
    envie de commiter ».
    """

    reason: str | None
    reports: tuple[FileReport, ...] = ()


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

    async def resolve_freezable(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> FreezeBlock:
        """Ce qui empêche d'enregistrer une version, et pourquoi, SANS avoir à l'essayer.

        Demandé par Gael le 25/10/2026 : l'écran grisait le bouton sur les seuls droits,
        et laissait cliquer ce que le serveur allait refuser. Les raisons de refus sont
        celles de `resolve_save`, lues ici par le MÊME code — une règle recopiée dans
        l'écran dériverait de celle qui refuse vraiment.

        **Le paramétrage est VALIDÉ ici depuis le 01/11/2026** (Gael : « il faudrait que
        le message d'erreur arrive avant que j'aie envie de commiter »). Jusque-là, la
        validation n'avait lieu qu'à l'enregistrement : on apprenait qu'un fichier ne
        passait pas les règles après avoir voulu figer, parfois après avoir publié pour
        rien. Elle lit la copie DÉJÀ sur disque — le coût cher, le `checkout`, est payé
        de toute façon par cette route.

        L'ordre des raisons est celui de `resolve_save`, et c'est volontaire : la raison
        rendue est celle que l'enregistrement opposerait VRAIMENT. Les rapports, eux,
        partent dans tous les cas — celui qui doit d'abord publier a le droit de savoir
        que le figement échouera ensuite.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            reports = tuple(await validate_branch(copy))
            if isinstance(copy, HeldCopy) and await copy.unpublished():
                return FreezeBlock("publication_requise", reports)
            mine, _ = await self._branch_versions(workspace_id, copy)
            last = mine[0] if mine else None
            if last is not None and await same_tree(copy, last.commit):
                return FreezeBlock("rien_a_figer", reports)
        return FreezeBlock("parametrage_invalide" if reports else None, reports)

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
