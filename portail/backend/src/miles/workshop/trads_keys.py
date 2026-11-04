from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.git.workcopy import WorkCopy
from miles.workshop.target import Gesture, WorkBranches
from miles.workshop.trads import culture_file, cultures_in
from miles.workshop.trads_keys_errors import KeyUnknownError, SlugTakenError
from miles.workshop.trads_keys_store import (
    checked_values,
    commit_or_refuse,
    matches,
    must_exist,
    read_keys,
    write_cultures,
)
from miles.workshop.trads_values import Key, checked_slug, values_of, values_text
from miles.workspaces.cultures import db_cultures

log = structlog.get_logger(__name__)

KEY_SAVED_EVENT = "trads_key.saved"
KEY_RENAMED_EVENT = "trads_key.renamed"
KEY_DELETED_EVENT = "trads_key.deleted"
EVENT_TYPES = frozenset({KEY_SAVED_EVENT, KEY_RENAMED_EVENT, KEY_DELETED_EVENT})
# Borne d'une page de clés : un contexte en porte des milliers au bout d'un an, et l'écran
# doit rester utilisable (critère 18).
PAGE_MAX = 200


@dataclass(frozen=True)
class Page:
    keys: list[Key]
    # Nombre total de clés du contexte, après filtre : l'écran sait alors combien il en
    # reste sans parcourir le dépôt une seconde fois.
    total: int


@dataclass(frozen=True)
class TradsKeysService:
    """Les clés d'un contexte et leurs valeurs par culture (story 289c8d9f)."""

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_page(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        context: str,
        *,
        branch: str | None = None,
        search: str = "",
        untranslated: str | None = None,
        offset: int = 0,
        limit: int = PAGE_MAX,
    ) -> Page:
        """Une page de clés, filtrée par slug et, si demandé, par culture non traduite."""
        cultures = await db_cultures(self.pool, workspace_id)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            await must_exist(copy, context)
            keys = await read_keys(copy, context, cultures)
        kept = [k for k in keys if matches(k, search, untranslated)]
        start = max(offset, 0)
        return Page(kept[start : start + min(max(limit, 1), PAGE_MAX)], len(kept))

    async def resolve_save(
        self,
        author: EventAuthor,
        workspace_id: str,
        context: str,
        slug: str,
        values: dict[str, str | None],
        *,
        branch: str | None = None,
        creating: bool = False,
    ) -> str:
        """Écrit les valeurs reçues, et SEULEMENT les fichiers des cultures touchées.

        Une saisie qui ne touche qu'une langue ne réécrit que son fichier : c'est le diff
        git qui rend ce dispositif relisible, et le réécrire en entier le perdrait. `None`
        pour une valeur vide la retire du fichier plutôt que d'y laisser une ligne vide.
        """
        slug = checked_slug(slug)
        cultures = await db_cultures(self.pool, workspace_id)
        touched = checked_values(values, cultures, creating=creating)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            await must_exist(copy, context)
            existing = await read_keys(copy, context, cultures)
            known = {k.slug for k in existing}
            if creating and slug in known:
                raise SlugTakenError(slug)
            if not creating and slug not in known:
                raise KeyUnknownError(slug)
            await write_cultures(copy, context, {slug: touched})
            commit = await commit_or_refuse(
                self.branches, copy, f"Traduction {context}/{slug}", author
            )
        await self._event(
            KEY_SAVED_EVENT, workspace_id, author, copy, context, {"key": slug, "new": creating}
        )
        log.info("trads_cle_enregistree", workspace=workspace_id, context=context, key=slug)
        return commit

    async def resolve_rename(
        self,
        author: EventAuthor,
        workspace_id: str,
        context: str,
        slug: str,
        new_slug: str,
        *,
        branch: str | None = None,
    ) -> str:
        """Renomme une clé dans TOUS les fichiers de cultures du contexte.

        Action distincte de l'édition, exprès : le slug est ce que le paramétrage
        référencera, et le jour où des références existeront personne ne saura dire
        lesquelles pointent quoi tant que le lien clé ↔ usage n'existe pas. L'écran
        avertit ; ici, on refuse au moins d'écraser une clé existante.
        """
        slug, new_slug = checked_slug(slug), checked_slug(new_slug)
        # Les cultures du DÉPÔT, pas celles du workspace : un fichier resté là après le
        # retrait d'une culture doit être renommé lui aussi, sinon la clé y garderait
        # l'ancien slug et réapparaîtrait dessous le jour où on remet la culture.
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await must_exist(copy, context)
            moved = False
            for culture in cultures_in(paths, context):
                path = culture_file(context, culture)
                values = values_of(path, await copy.read(path))
                if new_slug in values and slug != new_slug:
                    raise SlugTakenError(new_slug)
                if slug in values:
                    values[new_slug] = values.pop(slug)
                    await copy.write(path, values_text(values))
                    moved = True
            if not moved:
                raise KeyUnknownError(slug)
            commit = await commit_or_refuse(
                self.branches, copy, f"Renommage {context}/{slug} → {new_slug}", author
            )
        properties = {"key": slug, "new_key": new_slug}
        await self._event(KEY_RENAMED_EVENT, workspace_id, author, copy, context, properties)
        log.info("trads_cle_renommee", workspace=workspace_id, context=context, key=slug)
        return commit

    async def resolve_delete(
        self,
        author: EventAuthor,
        workspace_id: str,
        context: str,
        slug: str,
        *,
        branch: str | None = None,
    ) -> str:
        """Supprime la clé de tous les fichiers de cultures du contexte (critère 16)."""
        slug = checked_slug(slug)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await must_exist(copy, context)
            removed = 0
            for culture in cultures_in(paths, context):
                path = culture_file(context, culture)
                values = values_of(path, await copy.read(path))
                if values.pop(slug, None) is not None:
                    await copy.write(path, values_text(values))
                    removed += 1
            if removed == 0:
                raise KeyUnknownError(slug)
            commit = await commit_or_refuse(
                self.branches, copy, f"Suppression {context}/{slug}", author
            )
        properties = {"key": slug, "cultures": removed}
        await self._event(KEY_DELETED_EVENT, workspace_id, author, copy, context, properties)
        log.info("trads_cle_supprimee", workspace=workspace_id, context=context, key=slug)
        return commit

    async def _event(
        self,
        event_type: str,
        workspace_id: str,
        author: EventAuthor,
        copy: WorkCopy,
        context: str,
        properties: Mapping[str, object],
    ) -> None:
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {**properties, "context": context, "branch": copy.branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
