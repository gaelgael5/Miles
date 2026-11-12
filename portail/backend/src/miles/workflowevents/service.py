from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventChecker, NewEvent, ObjectRef

from miles.datamodels.grammar import Problem
from miles.datamodels.layout import SHARED, ModelEntry
from miles.datamodels.layout import entry_of as model_entry_of
from miles.datamodels.meta import meta_path, meta_text, read_version
from miles.datamodels.patch import patched
from miles.datamodels.schema import ModelSchema
from miles.git.workcopy import WorkCopy
from miles.workflowevents.layout import (
    EventEntry,
    checked_name,
    checked_scope,
    entry_of,
    event_path,
    visible,
)
from miles.workflowevents.schema import (
    EventGrammarError,
    draft,
    normalized,
    parse_event_schema,
)
from miles.workshop.domains import domains_in
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "workflow_event.created"
DELETED_EVENT = "workflow_event.deleted"
REPLACED_EVENT = "workflow_event.replaced"
EVENT_TYPES = frozenset({CREATED_EVENT, DELETED_EVENT, REPLACED_EVENT})


class EventNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class WorkflowEventsService:
    """Événements de workflow du workspace, écrits dans SA branche de travail.

    Des JSON Schema 2020-12 en YAML, comme les modèles de données, mais dans leur propre
    liste (Gael, 11/11/2026). Jamais en base, même en cache : le référentiel doit refléter
    exactement la version git — le moteur, lui, chargera ces fichiers tels quels.

    Il n'y a PAS de garde « utilisé par » à la suppression, et ce n'est pas un oubli :
    rien, dans le paramétrage que le portail écrit aujourd'hui, ne désigne un événement.
    Ce qui le désignera est le `DEFINE EVENT … AS @nom` d'un document de workflow, qui
    n'existe pas encore ; la garde naîtra avec lui, au même endroit que celle des modèles.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventChecker
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[EventEntry]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return [await _described(copy, e) for e in await _entries(copy)]

    async def resolve_get(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> tuple[EventEntry, str]:
        scope, name = checked_scope(scope), checked_name(name)
        entry = EventEntry(scope, name, event_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise EventNotFoundError(entry.path)
            return await _described(copy, entry), content

    async def resolve_declare(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        label: str,
        slug: str,
        *,
        branch: str | None = None,
    ) -> tuple[EventEntry, str | None]:
        """Déclare un événement par son libellé et son nom ; le schéma s'écrit à l'édition.

        Deux temps comme pour un modèle : ici l'identité, là la forme. Rejeu à
        l'identique : sans effet, None.
        """
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        return await self._create(
            author, workspace_id, scope, name, draft(scope, name, label), branch
        )

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[EventEntry, str | None]:
        """Écrit un événement depuis son schéma complet ; rejeu du même schéma : None.

        Sert la surface MCP, pas l'écran : un agent décrit l'événement en UN appel, là où
        la personne déclare puis complète. Aucune route HTTP ne l'expose, et c'est
        volontaire — une route que rien ne consomme est de la surface pour rien.
        """
        scope, name = checked_scope(scope), checked_name(name)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        parse_event_schema(content)
        return await self._create(
            author, workspace_id, scope, name, normalized(content, scope, name), branch
        )

    async def resolve_replace(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[EventEntry, str | None]:
        """Remplace le schéma d'un événement ; même schéma : sans effet, None.

        Le nom ne change pas : c'est le fichier et l'`$id`, que le système réécrit. La
        version monte de 1, tenue par le système — comme pour un modèle.
        """
        scope, name = checked_scope(scope), checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            entry, commit = await self._rewrite(copy, author, scope, name, content)
        if commit is None:
            return entry, None
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("evenement_de_workflow_remplace", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def resolve_patch(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        apply: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        branch: str | None = None,
    ) -> tuple[EventEntry, str | None]:
        """Modifie le schéma par une mutation locale (une propriété), en UN seul passage.

        Même geste que pour un modèle, et pour la même raison : un agent qui ajoute un
        champ n'a pas à renvoyer tout le document. Un seul `checkout`.
        """
        scope, name = checked_scope(scope), checked_name(name)
        entry = EventEntry(scope, name, event_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            text = await copy.read(entry.path)
            if text is None:
                raise EventNotFoundError(entry.path)
            entry, commit = await self._rewrite(copy, author, scope, name, patched(text, apply))
        if commit is None:
            return entry, None
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("evenement_de_workflow_remplace", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def _rewrite(
        self, copy: WorkCopy, author: EventAuthor, scope: str, name: str, content: str
    ) -> tuple[EventEntry, str | None]:
        """Le coeur d'un remplacement, dans une copie déjà ouverte ; None : rien à écrire."""
        schema = parse_event_schema(content)
        content = normalized(content, scope, name)
        entry = EventEntry(scope, name, event_path(scope, name))
        existing = await copy.read(entry.path)
        if existing is None:
            raise EventNotFoundError(entry.path)
        if existing == content:
            return await _described(copy, entry), None
        await _check_references(copy, entry, schema)
        version = read_version(await copy.read(meta_path(entry.path))) + 1
        await copy.write(entry.path, content)
        await copy.write(meta_path(entry.path), meta_text(version))
        commit = await self.branches.commit(copy, f"Événement {entry.path}", author)
        return await _described(copy, entry), commit

    async def _create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        branch: str | None,
    ) -> tuple[EventEntry, str | None]:
        schema = parse_event_schema(content)
        entry = EventEntry(scope, name, event_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            # Le domaine se déclare à part, comme pour un modèle : le créer ici au passage
            # ferait d'une faute de frappe un domaine de plus, sans que personne ne le voie.
            if scope != SHARED and scope not in domains_in(await copy.paths()):
                raise WorkspaceConflictError("domaine_inconnu")
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return await _described(copy, entry), None
                raise WorkspaceConflictError("nom_pris")
            await _check_references(copy, entry, schema)
            await copy.write(entry.path, content)
            # Un événement naît en version 1 : la version est au système, jamais au client.
            await copy.write(meta_path(entry.path), meta_text(1))
            commit = await self.branches.commit(copy, f"Événement {entry.path}", author)
            entry = await _described(copy, entry)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit, copy.branch)
        log.info("evenement_de_workflow_cree", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def resolve_delete(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> str:
        scope, name = checked_scope(scope), checked_name(name)
        entry = EventEntry(scope, name, event_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if entry not in await _entries(copy):
                raise EventNotFoundError(entry.path)
            await copy.remove(entry.path)
            if await copy.read(meta_path(entry.path)) is not None:
                await copy.remove(meta_path(entry.path))
            commit = await self.branches.commit(
                copy, f"Suppression de l'événement {entry.path}", author
            )
        await self._event(workspace_id, DELETED_EVENT, author, entry, commit, copy.branch)
        log.info("evenement_de_workflow_supprime", workspace=workspace_id, path=entry.path)
        return commit

    async def _event(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        entry: EventEntry,
        commit: str,
        branch: str,
    ) -> None:
        # Après le push : le journal dit ce qui est dans git. Le contenu n'y va pas, le
        # chemin et le commit suffisent à le retrouver.
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"path": entry.path, "commit": commit, "branch": branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def _check_references(copy: WorkCopy, entry: EventEntry, schema: ModelSchema) -> None:
    """Les `$ref` d'un événement désignent des MODÈLES de données, et ils doivent exister.

    Un événement décrit son payload métier, et rien n'interdit de le décrire avec un
    modèle déjà écrit — c'est même l'intérêt d'avoir le même dialecte. La règle de portée
    est celle des modèles entre eux : un transverse ne descend pas dans un domaine.
    """
    known = {(e.scope, e.name) for e in await _models(copy)}
    missing = [
        Problem(where, "modele_inconnu", f"{scope}/{name}")
        for where, (scope, name) in schema.references
        if (scope, name) not in known or not visible(entry, (scope, name))
    ]
    if missing:
        raise EventGrammarError(missing)


async def _entries(copy: WorkCopy) -> list[EventEntry]:
    return [e for e in map(entry_of, await copy.paths()) if e is not None]


async def _models(copy: WorkCopy) -> list[ModelEntry]:
    return [e for e in map(model_entry_of, await copy.paths()) if e is not None]


async def _described(copy: WorkCopy, entry: EventEntry) -> EventEntry:
    """L'événement avec son libellé (le `title` du schéma) et sa version (ses métadonnées)."""
    text = await copy.read(entry.path)
    base_only = False
    try:
        schema = parse_event_schema(text or "")
        label, base_only = schema.title, schema.empty
    except ValueError:
        # Illisible ou non conforme (retouché hors de Miles) : listé quand même, sans
        # libellé ; la validation de la branche dira pourquoi. Même repli que les modèles,
        # et c'en est un : ne pas lister reviendrait à cacher le fichier qui bloque la
        # version.
        label = None
    version = read_version(await copy.read(meta_path(entry.path)))
    return EventEntry(entry.scope, entry.name, entry.path, label, version or None, base_only)
