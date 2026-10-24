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
from miles.datamodels.schema import target_of
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.sources.layout import names_in, read_source, source_path
from miles.transform.chain import StepSpec, compile_chain
from miles.workshop.target import Gesture, WorkBranches, base_slug
from miles.workspaces.model import WorkspaceInputError, checked_label

log = structlog.get_logger(__name__)

SAVED_EVENT = "transformation_chain.saved"
DELETED_EVENT = "transformation_chain.deleted"
EVENT_TYPES = frozenset({SAVED_EVENT, DELETED_EVENT})


class ChainNotFoundError(Exception):
    pass


class ChainInUseError(Exception):
    """La chaîne est désignée par des flux : on nomme lesquels."""

    def __init__(self, users: list[str]) -> None:
        super().__init__(", ".join(users))
        self.users = users


@dataclass(frozen=True)
class StoredStep:
    name: str
    template: str
    target: str | None
    # URI des modèles que l'étape lit et produit (24/10/2026) ; None tant qu'ils ne
    # sont pas choisis. Ils ne changent rien à l'exécution : ils servent à l'écran, qui
    # en tire le gabarit du résultat et ce que l'étape transforme.
    source_model: str | None = None
    destination_model: str | None = None


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
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[StoredChain | str]:
        """Les chaînes lisibles, et le slug seul de celles dont l'enchaînement ne l'est pas."""
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            paths = await copy.paths()
            found: list[StoredChain | str] = []
            for slug in slugs_in(paths):
                stored = await stored_chain(copy, slug)
                found.append(stored if stored is not None else slug)
            return found

    async def resolve_get(
        self, viewer: EventAuthor, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> StoredChain:
        slug = checked_slug(slug)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            stored = await stored_chain(copy, slug)
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
    ) -> tuple[StoredChain, str | None]:
        """Crée ou remplace la chaîne ; rend (chaîne, commit). Rejeu à l'identique : None."""
        slug, label = checked_slug(slug), checked_label(label)
        docs = [
            StepDoc(
                s.name.strip(),
                (s.target or "").strip() or None,
                _model_ref(s.source_model),
                _model_ref(s.destination_model),
            )
            for s in steps
        ]
        checked_steps(docs)
        # Vérifiée avant tout accès au dépôt : une chaîne refusée ne coûte aucun clone.
        compile_chain([StepSpec(s.template, d.target) for s, d in zip(steps, docs, strict=True)])
        doc = ChainDoc(slug, label, tuple(docs))
        stored = StoredChain(
            slug,
            label,
            tuple(
                StoredStep(d.name, s.template, d.target, d.source_model, d.destination_model)
                for s, d in zip(steps, docs, strict=True)
            ),
        )
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            await _write(copy, doc, stored)
            changed = await copy.git("status", "--porcelain", "--", chain_dir(slug))
            if not changed.stdout.strip():
                return stored, None
            message = f"Chaîne de transformations {slug}"
            commit = await self.branches.commit(copy, message, author)
        await self._journal(SAVED_EVENT, workspace_id, author, slug, commit, copy.branch)
        log.info("chaine_enregistree", workspace=workspace_id, slug=slug, steps=len(docs))
        return stored, commit

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> str:
        slug = checked_slug(slug)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await copy.paths()
            files = files_of(paths, slug)
            if not files:
                raise ChainNotFoundError(slug)
            # Une chaîne désignée par une source ne se supprime pas : la source cesserait de
            # se vérifier, et son prochain import échouerait loin de la cause.
            users = [
                name
                for name in names_in(paths)
                if (doc := read_source(await copy.read(source_path(name)))) and doc.chain == slug
            ]
            if users:
                raise ChainInUseError(users)
            for name in files:
                await copy.remove(f"{chain_dir(slug)}/{name}")
            commit = await self.branches.commit(copy, f"Suppression de la chaîne {slug}", author)
        await self._journal(DELETED_EVENT, workspace_id, author, slug, commit, copy.branch)
        log.info("chaine_supprimee", workspace=workspace_id, slug=slug)
        return commit

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

    async def resolve_sample(
        self, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> str | None:
        """L'échantillon de test enregistré pour cette chaîne sur cette branche."""
        where = await self._sample_key(workspace_id, slug, branch)
        found = await self.pool.fetchval(
            "SELECT sample FROM chain_samples"
            " WHERE workspace_id = $1 AND branch_slug = $2 AND chain_slug = $3",
            *where,
        )
        return None if found is None else str(found)

    async def resolve_save_sample(
        self,
        author: EventAuthor,
        workspace_id: str,
        slug: str,
        sample: str,
        *,
        branch: str | None = None,
    ) -> None:
        """Enregistre l'échantillon ; un second écrase le premier, sans event au journal.

        Pas d'event : un cas d'essai n'est pas une modification du paramétrage, et le
        journal répond à « qui a changé quoi » dans ce qui est servi aux terminaux.
        """
        workspace_id, branch_slug, slug = await self._sample_key(workspace_id, slug, branch)
        await self.pool.execute(
            "INSERT INTO chain_samples (workspace_id, branch_slug, chain_slug, sample,"
            " updated_at, updated_by_directory, updated_by_subject)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7)"
            " ON CONFLICT (workspace_id, branch_slug, chain_slug) DO UPDATE SET"
            " sample = EXCLUDED.sample, updated_at = EXCLUDED.updated_at,"
            " updated_by_directory = EXCLUDED.updated_by_directory,"
            " updated_by_subject = EXCLUDED.updated_by_subject",
            workspace_id,
            branch_slug,
            slug,
            sample,
            self.now(),
            author.directory,
            author.subject,
        )

    async def resolve_clear_sample(
        self, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> None:
        where = await self._sample_key(workspace_id, slug, branch)
        await self.pool.execute(
            "DELETE FROM chain_samples"
            " WHERE workspace_id = $1 AND branch_slug = $2 AND chain_slug = $3",
            *where,
        )

    async def _sample_key(
        self, workspace_id: str, slug: str, branch: str | None
    ) -> tuple[str, str, str]:
        """(workspace, branche, chaîne) — la branche absente désignant la base.

        Passe par base_workspace : c'est lui qui refuse un workspace inconnu ou sans
        branche de travail, et l'échantillon ne doit pas être le seul chemin qui
        réponde sur un workspace auquel on n'a rien à faire.
        """
        workspace = await self.branches.base_workspace(workspace_id)
        chosen = (branch or "").strip() or base_slug(workspace) or ""
        # L'existence de la chaîne n'est pas vérifiée : il faudrait un clone pour une
        # donnée qui ne vit qu'en base, et un échantillon orphelin ne nuit à personne.
        return workspace.id, chosen, checked_slug(slug)


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


def _model_ref(raw: str | None) -> str | None:
    """Le modèle choisi, ou None ; une référence qui ne désigne rien est refusée ici.

    Refusée à l'écriture plutôt qu'à la relecture : une chaîne écrite avec une référence
    cassée deviendrait illisible, et le refus arriverait trop tard pour dire quoi faire.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if target_of(value) is None:
        raise WorkspaceInputError("modele", "inconnu")
    return value


async def stored_chain(copy: WorkCopy, slug: str) -> StoredChain | None:
    doc = read_chain(await copy.read(chain_path(slug)))
    if doc is None or doc.slug != slug:
        return None
    steps = []
    for step in doc.steps:
        template = await copy.read(template_path(slug, step))
        if template is None:
            return None
        steps.append(
            StoredStep(step.name, template, step.target, step.source_model, step.destination_model)
        )
    return StoredChain(doc.slug, doc.label, tuple(steps))
