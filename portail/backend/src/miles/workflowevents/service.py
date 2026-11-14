from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.catalog import EventCatalog, EventShape, closed_block
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef

from miles.datamodels.grammar import Problem
from miles.datamodels.layout import SHARED, ModelEntry, model_path
from miles.datamodels.layout import entry_of as model_entry_of
from miles.datamodels.schema import parse_schema
from miles.event_shapes import GESTURE, NAME
from miles.git.workcopy import WorkCopy
from miles.workflowevents.dsl import EventType, fragment_path, parse, render, scope_of
from miles.workflowevents.layout import (
    checked_model,
    checked_name,
    checked_scope,
    visible,
)
from miles.workflowevents.schema import EventModelError, dedup_problems, payload_problems
from miles.workshop.domains import domains_in
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "workflow_event.created"
DELETED_EVENT = "workflow_event.deleted"
REPLACED_EVENT = "workflow_event.replaced"
# Les types d'event de WORKFLOW déclarés dans le dépôt du workspace — à ne pas confondre
# avec les events du journal, qui sont ce que ce bloc décrit.
#
# `path` était le fichier du schéma jusqu'au 13/11/2026 ; c'est maintenant l'ARTEFACT du
# périmètre, qui porte toutes ses déclarations. D'où `event` à côté : sans lui, trois
# gestes sur trois types du même périmètre auraient tous le même bloc, et le journal ne
# dirait plus lequel a bougé.
_DECLARATION: dict[str, object] = {"path": NAME, "event": NAME, **GESTURE}
EVENT_SHAPES = (
    EventShape(CREATED_EVENT, "Type d'event de workflow déclaré", closed_block(_DECLARATION)),
    EventShape(DELETED_EVENT, "Type d'event de workflow supprimé", closed_block(_DECLARATION)),
    EventShape(REPLACED_EVENT, "Type d'event de workflow modifié", closed_block(_DECLARATION)),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)


class EventTypeNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class DeclaredType:
    """Un type d'event tel que l'artefact de son périmètre le déclare."""

    scope: str  # « shared », ou le nom du domaine
    name: str
    label: str
    # (portée, nom) du modèle qui décrit le payload, et son chemin : l'écran et la surface
    # MCP désignent un modèle par son chemin de dépôt, comme partout ailleurs.
    model: tuple[str, str]
    model_path: str
    unique: tuple[str, ...] = field(default=())
    # Le modèle désigné manque sur la branche. RENDU plutôt que refusé : une liste doit
    # montrer une déclaration orpheline — c'est ce qui bloque l'enregistrement d'une
    # version —, jamais la cacher.
    model_missing: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class WorkflowEventsService:
    """Types d'event de workflow du workspace, déclarés dans SA branche de travail.

    Depuis le 13/11/2026, un type d'event n'est plus un fichier : c'est un `DEFINE EVENT`
    de l'artefact de son périmètre (`shared/shared.wf`, `domains/<d>/<d>.wf`), et le
    payload qu'il décrit est un modèle de données ordinaire. Jamais en base, même en
    cache : le référentiel doit refléter exactement la version git — le moteur, lui,
    chargera ces fichiers tels quels.

    Conséquence assumée du renversement : un storage ou une source peut désormais désigner
    le modèle d'un type d'event. La liste séparée l'interdisait ; rien ne le justifiait une
    fois que la déclaration, et non le rangement, dit ce qu'est un type d'event.

    Il n'y a PAS de garde « utilisé par » à la suppression d'un type, et ce n'est pas un
    oubli : rien, dans le paramétrage que le portail écrit aujourd'hui, ne désigne un type
    d'event. Ce qui le désignera est le `ON EVENT` d'un document de workflow, qui n'existe
    pas encore ; la garde naîtra avec lui.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[DeclaredType]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return await _declared(copy)

    async def resolve_get(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> DeclaredType:
        scope, name = checked_scope(scope), checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            found = [d for d in await _declared(copy) if (d.scope, d.name) == (scope, name)]
        if not found:
            raise EventTypeNotFoundError(name)
        return found[0]

    async def resolve_declare(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        label: str,
        slug: str,
        model: tuple[str, str],
        unique: Sequence[str] = (),
        *,
        branch: str | None = None,
    ) -> tuple[DeclaredType, str | None]:
        """Déclare un type d'event dans l'artefact de son périmètre.

        Rejeu à l'identique : sans effet, et le commit rendu est None.
        """
        declared = await self._checked(scope, label, slug, model, unique)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            await self._check_against_branch(copy, declared)
            existing = await _declared(copy)
            same = [d for d in existing if (d.scope, d.name) == (declared.scope, declared.name)]
            if same:
                if same[0] == declared:
                    return same[0], None
                raise WorkspaceConflictError("nom_pris")
            commit = await self._rewrite(
                copy, author, declared.scope, [*_own(existing, declared.scope), declared]
            )
        await self._event(workspace_id, CREATED_EVENT, author, declared, commit, copy.branch)
        log.info("type_d_event_declare", workspace=workspace_id, event=declared.name)
        return declared, commit

    async def resolve_replace(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        label: str,
        model: tuple[str, str],
        unique: Sequence[str] = (),
        *,
        branch: str | None = None,
    ) -> tuple[DeclaredType, str | None]:
        """Change le libellé, le modèle ou les clés d'unicité d'un type déjà déclaré.

        Le nom ne change pas : c'est lui qu'un script de workflow écrit, et le renommer
        casserait tout `ON EVENT` qui le nomme sans qu'aucun des deux documents paraisse
        faux. Un renommage se fait en déclarant l'autre nom et en supprimant celui-ci.
        """
        declared = await self._checked(scope, label, name, model, unique)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            # L'existence AVANT les règles du modèle : sur un type qu'on n'a pas, un refus
            # qui parle du modèle désigné envoie corriger le mauvais document.
            existing = await _declared(copy)
            if not any((d.scope, d.name) == (declared.scope, declared.name) for d in existing):
                raise EventTypeNotFoundError(name)
            await self._check_against_branch(copy, declared)
            kept = [
                declared if d.name == declared.name else d for d in _own(existing, declared.scope)
            ]
            if kept == _own(existing, declared.scope):
                return declared, None
            commit = await self._rewrite(copy, author, declared.scope, kept)
        await self._event(workspace_id, REPLACED_EVENT, author, declared, commit, copy.branch)
        log.info("type_d_event_modifie", workspace=workspace_id, event=declared.name)
        return declared, commit

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
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await _declared(copy)
            gone = [d for d in existing if (d.scope, d.name) == (scope, name)]
            if not gone:
                raise EventTypeNotFoundError(name)
            kept = [d for d in _own(existing, scope) if d.name != name]
            commit = await self._rewrite(copy, author, scope, kept)
        await self._event(workspace_id, DELETED_EVENT, author, gone[0], commit, copy.branch)
        log.info("type_d_event_supprime", workspace=workspace_id, event=name)
        return commit

    async def _checked(
        self,
        scope: str,
        label: str,
        slug: str,
        model: tuple[str, str],
        unique: Sequence[str],
    ) -> DeclaredType:
        """La saisie, vérifiée AVANT tout accès au dépôt : un refus ne coûte aucun clone."""
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        model_scope, model_name = checked_model(*model)
        if not visible(scope, (model_scope, model_name)):
            # Un périmètre transverse qui désignerait un modèle de domaine cesserait
            # d'être transverse, et le moteur chargerait un schéma qu'un autre domaine ne
            # voit pas. Même règle que les modèles entre eux.
            raise WorkspaceConflictError("portee_du_modele")
        return DeclaredType(
            scope,
            name,
            label,
            (model_scope, model_name),
            model_path(model_scope, model_name),
            tuple(unique),
        )

    async def _check_against_branch(self, copy: WorkCopy, declared: DeclaredType) -> None:
        """Ce qui ne se vérifie qu'avec la branche sous les yeux : domaine, modèle, clés."""
        if declared.scope != SHARED and declared.scope not in domains_in(await copy.paths()):
            # Le domaine se déclare à part, comme pour un modèle : le créer ici au passage
            # ferait d'une faute de frappe un domaine de plus, sans que personne ne le voie.
            raise WorkspaceConflictError("domaine_inconnu")
        text = await copy.read(declared.model_path)
        if text is None:
            raise EventModelError([Problem("model", "modele_inconnu", declared.model_path)])
        schema = parse_schema(text)
        problems = payload_problems(text, schema) + dedup_problems(declared.unique, schema)
        if problems:
            raise EventModelError(problems)
        # Un nom unique dans TOUT le workspace, et non dans le seul périmètre : un script
        # qui `INCLUDE` deux artefacts déclarant le même nom ne charge pas du tout — le
        # moteur lève « event 'a' is already declared » pendant la visite (mesuré le
        # 14/11/2026). Refuser ici, c'est refuser au geste plutôt qu'au chargement.
        ailleurs = [
            d
            for d in await _declared(copy)
            if d.name == declared.name and d.scope != declared.scope
        ]
        if ailleurs:
            raise WorkspaceConflictError("nom_pris_ailleurs")

    async def _rewrite(
        self, copy: WorkCopy, author: EventAuthor, scope: str, types: list[DeclaredType]
    ) -> str:
        """Réécrit l'artefact d'un périmètre, ou le supprime quand il ne reste rien.

        Un artefact sans déclaration est une erreur de syntaxe pour le moteur : le laisser
        derrière, vide, ferait échouer le chargement de tout le répertoire. On retire donc
        le fichier plutôt que de l'écrire vide.
        """
        path = fragment_path(scope)
        text = render(scope, [EventType(d.name, d.label, d.model, d.unique) for d in types])
        if text:
            await copy.write(path, text)
        elif await copy.read(path) is not None:
            await copy.remove(path)
        return await self.branches.commit(copy, f"Types d'event {path}", author)

    async def _event(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        declared: DeclaredType,
        commit: str,
        branch: str,
    ) -> None:
        # Après le push : le journal dit ce qui est dans git. Le contenu n'y va pas,
        # l'artefact, le nom déclaré et le commit suffisent à le retrouver.
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {
                "path": fragment_path(declared.scope),
                "event": declared.name,
                "commit": commit,
                "branch": branch,
            },
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _own(declared: list[DeclaredType], scope: str) -> list[DeclaredType]:
    return [d for d in declared if d.scope == scope]


async def _declared(copy: WorkCopy) -> list[DeclaredType]:
    """Tous les types déclarés sur la branche, périmètre par périmètre.

    Un artefact illisible fait lever `FragmentError` : on ne rend PAS une liste partielle.
    Masquer un périmètre entier parce que son fichier a été retouché hors de Miles ferait
    croire que ses types ont disparu, et un geste de déclaration écrirait alors par-dessus
    ce qu'on n'a pas su relire.
    """
    paths = await copy.paths()
    known = {(e.scope, e.name) for e in _models(paths)}
    found: list[DeclaredType] = []
    for path in sorted(paths):
        scope = scope_of(path)
        if scope is None:
            continue
        for declared in parse(await copy.read(path) or ""):
            found.append(
                DeclaredType(
                    scope,
                    declared.name,
                    declared.label,
                    declared.model,
                    model_path(*declared.model),
                    declared.unique,
                    declared.model not in known,
                )
            )
    return found


def _models(paths: list[str]) -> list[ModelEntry]:
    return [e for e in map(model_entry_of, paths) if e is not None]
