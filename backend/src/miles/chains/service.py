from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.chains.layout import (
    CHAIN_FILE,
    ChainDoc,
    StepDoc,
    chain_dir,
    chain_path,
    chain_text,
    checked_slug,
    checked_steps,
    files_of,
    read_chain,
    slugs_in,
    template_path,
)
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.transform.chain import StepSpec, compile_chain
from miles.workshop.target import WorkBranches
from miles.workspaces.model import checked_label

log = structlog.get_logger(__name__)

SAVED_EVENT = "transformation_chain.saved"
DELETED_EVENT = "transformation_chain.deleted"
EVENT_TYPES = frozenset({SAVED_EVENT, DELETED_EVENT})


class ChainNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class StoredStep:
    name: str
    template: str
    target: str | None


@dataclass(frozen=True)
class StoredChain:
    slug: str
    label: str
    steps: tuple[StoredStep, ...]


@dataclass(frozen=True)
class ChainsService:
    """Chaînes de transformations de la branche (story c1e4424b).

    La chaîne est un objet autonome, nommé par son slug : les flux (sources de données,
    MQTT, webservices) la désigneront. Elle s'enregistre entière, enchaînement et
    templates d'un même commit, et seulement si toutes ses étapes passent la vérification.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, workspace_id: str, *, branch: str | None = None
    ) -> list[StoredChain | str]:
        """Les chaînes lisibles, et le slug seul de celles dont l'enchaînement ne l'est pas."""
        async with self.branches.checkout(workspace_id, branch) as copy:
            paths = await copy.paths()
            found: list[StoredChain | str] = []
            for slug in slugs_in(paths):
                stored = await _stored(copy, slug)
                found.append(stored if stored is not None else slug)
            return found

    async def resolve_get(
        self, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> StoredChain:
        slug = checked_slug(slug)
        async with self.branches.checkout(workspace_id, branch) as copy:
            stored = await _stored(copy, slug)
        if stored is None:
            raise ChainNotFoundError(slug)
        return stored

    async def resolve_save(
        self,
        author: EventAuthor,
        workspace_id: str,
        slug: str,
        label: str,
        steps: list[StoredStep],
        *,
        branch: str | None = None,
    ) -> tuple[StoredChain, bool]:
        """Crée ou remplace la chaîne ; rend (chaîne, déjà_là). Rejeu à l'identique : sans effet."""
        slug, label = checked_slug(slug), checked_label(label)
        docs = [StepDoc(s.name.strip(), (s.target or "").strip() or None) for s in steps]
        checked_steps(docs)
        # Vérifiée avant tout accès au dépôt : une chaîne refusée ne coûte aucun clone.
        compile_chain([StepSpec(s.template, d.target) for s, d in zip(steps, docs, strict=True)])
        doc = ChainDoc(slug, label, tuple(docs))
        stored = StoredChain(
            slug,
            label,
            tuple(
                StoredStep(d.name, s.template, d.target) for s, d in zip(steps, docs, strict=True)
            ),
        )
        async with self.branches.checkout(workspace_id, branch) as copy:
            await _write(copy, doc, stored)
            changed = await copy.git("status", "--porcelain", "--", chain_dir(slug))
            if not changed.stdout.strip():
                return stored, True
            message = f"Chaîne de transformations {slug}"
            commit = await self.branches.push(copy, message, author)
        await self._journal(SAVED_EVENT, workspace_id, author, slug, commit, copy.branch)
        log.info("chaine_enregistree", workspace=workspace_id, slug=slug, steps=len(docs))
        return stored, False

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> None:
        slug = checked_slug(slug)
        async with self.branches.checkout(workspace_id, branch) as copy:
            files = files_of(await copy.paths(), slug)
            if not files:
                raise ChainNotFoundError(slug)
            for name in files:
                await copy.remove(f"{chain_dir(slug)}/{name}")
            commit = await self.branches.push(copy, f"Suppression de la chaîne {slug}", author)
        await self._journal(DELETED_EVENT, workspace_id, author, slug, commit, copy.branch)
        log.info("chaine_supprimee", workspace=workspace_id, slug=slug)

    async def _journal(
        self,
        kind: str,
        workspace_id: str,
        author: EventAuthor,
        slug: str,
        commit: str,
        branch: str,
    ) -> None:
        properties = {"slug": slug, "commit": commit, "branch": branch}
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def _write(copy: WorkCopy, doc: ChainDoc, stored: StoredChain) -> None:
    kept = {CHAIN_FILE, *(s.template_file for s in doc.steps)}
    # Les templates d'étapes retirées partent avec l'enchaînement qui ne les cite plus.
    for name in files_of(await copy.paths(), doc.slug):
        if name not in kept:
            await copy.remove(f"{chain_dir(doc.slug)}/{name}")
    await copy.write(chain_path(doc.slug), chain_text(doc))
    for step_doc, step in zip(doc.steps, stored.steps, strict=True):
        await copy.write(template_path(doc.slug, step_doc), step.template)
    await copy.git("add", "-A", "--", chain_dir(doc.slug))


async def _stored(copy: WorkCopy, slug: str) -> StoredChain | None:
    doc = read_chain(await copy.read(chain_path(slug)))
    if doc is None or doc.slug != slug:
        return None
    steps = []
    for step in doc.steps:
        template = await copy.read(template_path(slug, step))
        if template is None:
            return None
        steps.append(StoredStep(step.name, template, step.target))
    return StoredChain(doc.slug, doc.label, tuple(steps))
