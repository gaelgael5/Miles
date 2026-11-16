from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.catalog import EventCatalog, EventShape, closed_block
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef

from miles.event_shapes import GESTURE, NAME
from miles.workflowevents.dsl import DslProblem
from miles.workflows.dsl import Header, ScriptError, read_header, render_new
from miles.workflows.layout import (
    checked_against_scopes,
    checked_name,
    names_in,
    workflow_path,
)
from miles.workshop.domains import domains_in
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "workflow.created"
DELETED_EVENT = "workflow.deleted"
_WORKFLOW: dict[str, object] = {"workflow": NAME, **GESTURE}
EVENT_SHAPES = (
    EventShape(CREATED_EVENT, "Workflow créé", closed_block(_WORKFLOW)),
    EventShape(DELETED_EVENT, "Workflow supprimé", closed_block(_WORKFLOW)),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)


class WorkflowNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class Listed:
    """Un workflow de la branche, lisible ou non.

    Les manquements sont RENDUS plutôt que levés : un script cassé doit se voir dans la
    liste — c'est lui qui empêchera d'enregistrer une version —, jamais la faire
    disparaître. Même choix que pour une déclaration de storage illisible.
    """

    name: str
    header: Header | None
    problems: tuple[DslProblem, ...] = field(default=())


@dataclass(frozen=True)
class WorkflowsService:
    """Les scripts de workflow d'une branche de travail (story 69036d69).

    Un workflow est un script COMPLET du DSL d'`urban-workflow` : il `INCLUDE` les
    artefacts des périmètres dont il consomme les types d'event, puis déclare ses états
    et ses transitions. Il vit dans git comme le reste du paramétrage, et jamais en base,
    même en cache : le moteur chargera ces fichiers tels quels.

    Ce que ce service NE fait pas, et c'est la frontière posée par Gael le 12/11/2026 :
    il n'évalue rien. « c'est environnement qui fera les évaluations du workflow quand
    les events seront traités. » Ici on écrit et on diagnostique.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[Listed]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            found = []
            for name in names_in(await copy.paths()):
                found.append(_listed(name, await copy.read(workflow_path(name)) or ""))
            return found

    async def resolve_get(
        self, viewer: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> tuple[Listed, str]:
        """Le workflow et son TEXTE : l'écran d'écriture part du fichier, pas d'un résumé."""
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            text = await copy.read(workflow_path(name))
        if text is None:
            raise WorkflowNotFoundError(name)
        return _listed(name, text), text

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        name: str,
        label: str,
        *,
        branch: str | None = None,
    ) -> Header:
        """Crée un workflow réduit à son identité, et le fichier est chargeable tel quel."""
        # Vérifiés avant tout accès au dépôt : un nom mal formé ne coûte aucun clone.
        name = checked_name(name)
        label = checked_label(label)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await copy.paths()
            # Le nom d'un périmètre est refusé ici : voir `checked_against_scopes`, la
            # publication rassemble tout dans un répertoire plat et l'un écraserait l'autre.
            checked_against_scopes(name, domains_in(paths))
            if name in names_in(paths):
                raise WorkspaceConflictError("nom_pris")
            await copy.write(workflow_path(name), render_new(name, label))
            commit = await self.branches.commit(copy, f"Workflow {name}", author)
        await self._journal(CREATED_EVENT, workspace_id, author, name, commit, copy.branch)
        log.info("workflow_cree", workspace=workspace_id, workflow=name)
        return Header(name=name, label=label, version=None)

    async def resolve_delete(
        self, author: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> None:
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if await copy.read(workflow_path(name)) is None:
                raise WorkflowNotFoundError(name)
            # Aucune garde « utilisé par » : rien, dans le paramétrage écrit à ce jour, ne
            # désigne un workflow. C'est le module d'environnement qui en chargera un, et
            # il le fera depuis une version figée — pas depuis cette branche.
            await copy.remove(workflow_path(name))
            commit = await self.branches.commit(copy, f"Suppression du workflow {name}", author)
        await self._journal(DELETED_EVENT, workspace_id, author, name, commit, copy.branch)
        log.info("workflow_supprime", workspace=workspace_id, workflow=name)

    async def _journal(
        self, kind: str, workspace_id: str, author: EventAuthor, name: str, commit: str, branch: str
    ) -> None:
        properties = {"workflow": name, "commit": commit, "branch": branch}
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _listed(name: str, text: str) -> Listed:
    """Le workflow d'un fichier, ou ses manquements — et le NOM reste celui du fichier.

    Le nom vient du fichier et non du `NAME` du script, même quand le script se relit :
    c'est le fichier qu'on supprime et qu'on rouvre. Un script dont le `NAME` ne
    correspond pas à son fichier est un écart RÉEL, et c'est la validation de branche qui
    le rapporte — pas la liste, qui mentirait sur le nom de l'un ou de l'autre.
    """
    try:
        return Listed(name, read_header(text))
    except ScriptError as exc:
        return Listed(name, None, exc.problems)
