from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.git.workcopy import WorkCopy
from miles.workshop.target import Gesture, WorkBranches
from miles.workshop.trads import (
    TRADS,
    Context,
    checked_context,
    checked_label,
    context_file,
    context_text,
    contexts_in,
    culture_file,
    cultures_in,
    file_context_keys,
    file_contexts,
    keys_of,
    label_of,
)
from miles.workshop.trads_coverage import DEFAULT_LOW_PERCENT, Coverage, rolled_up
from miles.workspaces.cultures import checked_culture, db_cultures
from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError

log = structlog.get_logger(__name__)

CREATED_EVENT = "trads_context.created"
RELABELLED_EVENT = "trads_context.relabelled"
DELETED_EVENT = "trads_context.deleted"
OBSOLETE_REMOVED_EVENT = "trads_context.obsolete_removed"
EVENT_TYPES = frozenset({CREATED_EVENT, RELABELLED_EVENT, DELETED_EVENT, OBSOLETE_REMOVED_EVENT})


class ContextTakenError(WorkspaceConflictError):
    """Nom technique déjà pris : on nomme le contexte qui le porte (critère 3).

    Son LIBELLÉ, et pas seulement son nom : c'est ce qui permet à l'écran de dire de quel
    contexte il s'agit, là où le nom technique seul répète ce que la personne a saisi.
    """

    def __init__(self, label: str) -> None:
        super().__init__("contexte_pris")
        self.label = label


@dataclass(frozen=True)
class Removal:
    """Ce qu'une suppression de contexte emporte, pour que la confirmation le dise."""

    keys: int
    values: int


@dataclass(frozen=True)
class TradsService:
    """Contextes du référentiel de traductions : les répertoires de `trads/` (story 623898d1).

    Aucune liste en base : le dépôt fait foi, un répertoire créé à la main apparaît, et
    rien ne peut le contredire. Le libellé lui-même vit dans la branche.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Seuil de signalement d'une couverture très basse, en pour cent (story 82e60880,
    # critère 8). Porté par le service et non lu au point d'usage : c'est lui qui décide,
    # et un test peut alors mesurer la décision sans monter une configuration.
    low_coverage_percent: int = DEFAULT_LOW_PERCENT

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[Context]:
        cultures = await db_cultures(self.pool, workspace_id)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return await file_contexts(copy.read, await copy.paths(), list(cultures.all))

    async def resolve_coverage(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> Coverage:
        """La couverture de la branche : l'ensemble d'abord, puis contexte par contexte.

        Un SEUL parcours du dépôt pour les deux niveaux : le détail par contexte est
        exactement ce qu'on somme pour obtenir l'ensemble. Deux lectures auraient refait
        le travail entier, et auraient pu rendre deux états différents si quelqu'un
        pousse sur la branche entre les deux.
        """
        cultures = await db_cultures(self.pool, workspace_id)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            contexts = await file_contexts(copy.read, await copy.paths(), list(cultures.all))
            return rolled_up(
                contexts,
                cultures.default,
                cultures.all,
                # La branche que le dépôt a réellement ouverte, pas celle demandée : sans
                # branche, `checkout` prend la branche de base, et l'écran doit nommer
                # celle qu'il montre.
                branch=copy.branch,
                threshold=self.low_coverage_percent,
            )

    async def resolve_add(
        self,
        author: EventAuthor,
        workspace_id: str,
        name: str,
        label: str,
        *,
        branch: str | None = None,
    ) -> str | None:
        """Crée le contexte et son répertoire ; s'il existe déjà : sans effet, None."""
        name, label = _checked(name, label)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if name in contexts_in(await copy.paths()):
                meta = context_file(name)
                raise ContextTakenError(label_of(meta, await copy.read(meta), name))
            # Le fichier de métadonnées EST ce qui fait exister le répertoire : git ne
            # garde pas un répertoire vide, et le libellé doit y vivre de toute façon.
            await copy.write(context_file(name), context_text(label))
            commit = await self.branches.commit(copy, f"Contexte de traduction {name}", author)
            await self._event(CREATED_EVENT, workspace_id, author, copy, {"context": name})
        log.info("contexte_trads_cree", workspace=workspace_id, context=name)
        return commit

    async def resolve_relabel(
        self,
        author: EventAuthor,
        workspace_id: str,
        name: str,
        label: str,
        *,
        branch: str | None = None,
    ) -> str:
        """Change le libellé. Le NOM TECHNIQUE, lui, ne se change jamais.

        Il entre dans le chemin sur disque et dans tout ce qui référencera ses clés ; le
        renommer déplacerait des fichiers et casserait des références, sans qu'on sache
        lesquelles tant que le lien clé ↔ usage n'existe pas. Même raison que pour le slug
        d'un contrat OpenAPI. Il n'y a donc aucune route pour le changer.
        """
        name, label = _checked(name, label)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            await _must_exist(copy, name)
            await copy.write(context_file(name), context_text(label))
            commit = await self.branches.commit(copy, f"Libellé du contexte {name}", author)
            await self._event(RELABELLED_EVENT, workspace_id, author, copy, {"context": name})
        log.info("contexte_trads_renomme", workspace=workspace_id, context=name)
        return commit

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> tuple[str, Removal]:
        """Supprime le contexte et TOUTES ses clés ; rend le commit et ce qui a disparu.

        Rien n'est perdu pour autant : c'est un commit sur la branche de travail, donc la
        suppression se relit, se revoit et se défait comme toute autre modification.
        """
        name = _checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await _must_exist(copy, name)
            removal = await _removal(copy, name, paths)
            for path in paths:
                if path.startswith(f"{TRADS}{name}/"):
                    await copy.remove(path)
            commit = await self.branches.commit(copy, f"Suppression du contexte {name}", author)
            properties = {"context": name, "keys": removal.keys, "values": removal.values}
            await self._event(DELETED_EVENT, workspace_id, author, copy, properties)
        log.info("contexte_trads_supprime", workspace=workspace_id, context=name)
        return commit, removal

    async def resolve_removal(
        self, viewer: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> Removal:
        """Ce qu'une suppression emporterait : l'écran le demande AVANT de confirmer."""
        name = _checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return await _removal(copy, name, await _must_exist(copy, name))

    async def resolve_delete_obsolete(
        self,
        author: EventAuthor,
        workspace_id: str,
        name: str,
        culture: str,
        *,
        branch: str | None = None,
    ) -> tuple[str, int]:
        """Supprime le fichier d'une culture que le workspace ne retient plus.

        C'est le seul « obsolète » que le produit crée lui-même : retirer une culture
        garde ses fichiers, exprès, pour ne pas détruire un travail de traduction en
        décochant une case — mais rien ne permettait ensuite de faire le ménage.

        Une culture ENCORE au workspace est refusée : le geste est un nettoyage, et le
        laisser porter sur une traduction active en ferait une destruction silencieuse.
        """
        name, culture = _checked_name(name), checked_culture(culture)
        cultures = await db_cultures(self.pool, workspace_id)
        if culture in cultures.all:
            raise WorkspaceConflictError("culture_du_workspace")
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await _must_exist(copy, name)
            if culture not in cultures_in(paths, name):
                raise WorkspaceConflictError("culture_sans_fichier")
            path = culture_file(name, culture)
            values = len(keys_of(path, await copy.read(path)))
            await copy.remove(path)
            commit = await self.branches.commit(
                copy, f"Retrait des traductions {name}/{culture}", author
            )
            properties = {"context": name, "culture": culture, "values": values}
            await self._event(OBSOLETE_REMOVED_EVENT, workspace_id, author, copy, properties)
        log.info(
            "trads_culture_obsolete_retiree", workspace=workspace_id, context=name, culture=culture
        )
        return commit, values

    async def _event(
        self,
        event_type: str,
        workspace_id: str,
        author: EventAuthor,
        copy: WorkCopy,
        properties: dict[str, object],
    ) -> None:
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            properties | {"branch": copy.branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def _must_exist(copy: WorkCopy, name: str) -> list[str]:
    paths = await copy.paths()
    if name not in contexts_in(paths):
        raise WorkspaceConflictError("contexte_inconnu")
    return paths


async def _removal(copy: WorkCopy, name: str, paths: list[str]) -> Removal:
    """Clés du contexte, et valeurs toutes cultures confondues.

    Les deux, et non les seules clés : un contexte de dix clés traduites en cinq langues
    fait disparaître cinquante valeurs, et c'est ce nombre-là qui dit l'ampleur du geste.
    """
    cultures = cultures_in(paths, name)
    keys = await file_context_keys(copy.read, name, cultures)
    values = 0
    for culture in cultures:
        path = culture_file(name, culture)
        values += len(keys_of(path, await copy.read(path)))
    return Removal(len(keys), values)


def _checked_name(name: str) -> str:
    try:
        return checked_context(name)
    except ValueError:
        # Le nom devient un segment de chemin : refusé avant tout accès au dépôt.
        raise WorkspaceInputError("name", "forme") from None


def _checked(name: str, label: str) -> tuple[str, str]:
    try:
        return _checked_name(name), checked_label(label)
    except ValueError:
        raise WorkspaceInputError("label", "forme") from None
