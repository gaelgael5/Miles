from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.catalog import EventCatalog, EventShape, closed_block
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef

from miles.datamodels.events import CREATED_EVENT as MODEL_CREATED
from miles.datamodels.events import REPLACED_EVENT as MODEL_REPLACED
from miles.datamodels.events import ModelJournal
from miles.datamodels.grammar import Problem
from miles.datamodels.layout import SHARED, ModelEntry, model_path
from miles.datamodels.schema import draft, normalized, parse_schema
from miles.datamodels.writing import stage_new, write_replacement
from miles.event_shapes import GESTURE, NAME
from miles.git.workcopy import WorkCopy
from miles.workflowevents.artefact import rewrite
from miles.workflowevents.dsl import EventType, fragment_path
from miles.workflowevents.inheritance import (
    MAX_DEPTH,
    TOO_DEEP,
    ancestry,
    cycle_problems,
    loop_problems,
    parents_of,
    with_parent,
)
from miles.workflowevents.layout import (
    checked_model,
    checked_name,
    checked_scope,
    visible,
)
from miles.workflowevents.reading import (
    DeclaredType,
    Perimeter,
    declared_in,
    read_perimeters,
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
        """Tous les types de la branche, ou RIEN si un artefact ne se relit pas.

        Le tout-ou-rien reste la règle de CETTE lecture, et c'est elle que la surface MCP
        sert : un agent écrit, et une liste amputée l'amènerait à déclarer par-dessus un
        périmètre qu'on n'a pas su relire. L'écran, lui, lit par périmètre
        (`resolve_perimeters`) — il nomme le fichier fautif sans perdre le reste de
        l'arbre, ce qu'une liste plate ne sait pas faire.
        """
        return declared_in(await self.resolve_perimeters(viewer, workspace_id, branch=branch))

    async def resolve_perimeters(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> tuple[Perimeter, ...]:
        """Chaque périmètre de la branche, avec ses types ou ce qui empêche de les lire.

        UNE lecture de branche pour tout : la liste des périmètres, leurs déclarations et
        les modèles qui manquent. Le menu et l'écran partagent donc une requête, et un
        geste de branche par périmètre aurait coûté une ouverture par domaine.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return await read_perimeters(copy.read, await copy.paths())

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
            existing = await _declared(copy)
            await self._check_against_branch(copy, declared, existing)
            same = [d for d in existing if (d.scope, d.name) == (declared.scope, declared.name)]
            if same:
                if same[0] == declared:
                    return same[0], None
                raise WorkspaceConflictError("nom_pris")
            commit = await self._rewrite(
                copy, author, declared.scope, [*_own(existing, declared.scope), declared]
            )
            declared = await _with_parents(copy, declared)
        await self._event(workspace_id, CREATED_EVENT, author, declared, commit, copy.branch)
        log.info(
            "type_d_event_declare", workspace=workspace_id, scope=declared.scope, name=declared.name
        )
        return declared, commit

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        label: str,
        slug: str,
        parent: tuple[str, str] | None = None,
        unique: Sequence[str] = (),
        *,
        branch: str | None = None,
    ) -> tuple[DeclaredType, str]:
        """Crée un type d'event ET le modèle de son payload, qui hérite de `parent`.

        LE geste du 19/11/2026 : « dans le menu types d'events ce que l'on fait c'est
        ajouter et créer les events […] quand on créé un second event, il herite de ce
        premier event. » On ne choisit donc plus un modèle dans une liste — c'est
        `resolve_declare` qui le fait encore, pour un agent qui désigne un modèle existant.

        `parent` est un autre TYPE D'EVENT, ou `None` pour l'event de base : le moteur
        applique sa racine d'office, donc il n'y a alors aucun `$ref` à écrire (décision 2
        du 22/11/2026).

        Le payload porte le NOM de l'event, et ce n'est pas un hasard : il appartient à
        l'event depuis le renversement du 19/11, donc il n'y a aucun nom à choisir, et
        rien ne reste derrière qui ne se rattache à rien.

        UN SEUL commit pour les deux fichiers — le modèle et l'artefact. Deux commits
        laisseraient, si le second échouait, un modèle que rien ne déclare.
        """
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        model = checked_model(scope, name)
        entry = ModelEntry(*model, model_path(*model))
        declared = DeclaredType(scope, name, label, model, entry.path, tuple(unique))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await _declared(copy)
            await self._check_declaration(copy, declared, existing)
            if any((d.scope, d.name) == (scope, name) for d in existing):
                raise WorkspaceConflictError("nom_pris")
            parent_model = self._parent_model(declared, existing, parent)
            content = normalized(with_parent(draft(scope, name, label), parent_model), scope, name)
            await self._check_model(copy, declared, content, parent_model)
            # Tout est accepté : on écrit enfin. La copie de travail persiste d'un geste à
            # l'autre, donc une copie à moitié écrite serait committée par le suivant —
            # c'est la règle de `datamodels.writing`, et elle vaut ici aussi.
            written = await stage_new(copy, entry, content, parse_schema(content))
            commit = await self._rewrite(copy, author, scope, [*_own(existing, scope), declared])
        if written:
            # Pas de fait si rien n'est né : un modèle déjà là À L'IDENTIQUE — un type
            # supprimé puis recréé sous le même nom — n'est pas un modèle créé, et le
            # journal dit ce que git a reçu.
            await self._journal.db_write(
                workspace_id, MODEL_CREATED, author, entry, commit, copy.branch
            )
        await self._event(workspace_id, CREATED_EVENT, author, declared, commit, copy.branch)
        log.info("type_d_event_cree", workspace=workspace_id, scope=scope, name=name)
        parents = () if parent_model is None else (parent_model,)
        return replace(declared, parents=parents), commit

    async def resolve_reparent(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        parent: tuple[str, str] | None,
        *,
        branch: str | None = None,
    ) -> tuple[DeclaredType, str | None]:
        """Redirige l'héritage d'un type d'event vers un autre type, ou vers l'event de base.

        « cet heritage peut être redirigé sur un autre event présent sur le disque »
        (Gael, 19/11/2026). Ce qui change est UNE ligne du modèle de payload — son
        `allOf: $ref` —, et rien d'autre : c'est tout l'intérêt d'avoir posé l'héritage en
        `$ref` plutôt qu'en recopie des champs du parent.

        L'artefact du périmètre ne bouge pas, donc le fait journalisé est celui d'un
        MODÈLE remplacé, et non d'une déclaration modifiée : le journal dit ce que git a
        reçu. Rejeu à l'identique : sans effet, et le commit rendu est None.
        """
        scope, name = checked_scope(scope), checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            existing = await _declared(copy)
            found = [d for d in existing if (d.scope, d.name) == (scope, name)]
            if not found:
                raise EventTypeNotFoundError(name)
            declared = found[0]
            parent_model = self._parent_model(declared, existing, parent)
            text = await copy.read(declared.model_path)
            if text is None:
                raise EventModelError([Problem("model", "modele_inconnu", declared.model_path)])
            content = with_parent(text, parent_model)
            await self._check_model(copy, declared, content, parent_model)
            entry, commit = await write_replacement(
                copy, self.branches, author, *declared.model, content
            )
        parents = () if parent_model is None else (parent_model,)
        if commit is None:
            return replace(declared, parents=parents), None
        await self._journal.db_write(
            workspace_id, MODEL_REPLACED, author, entry, commit, copy.branch
        )
        log.info("heritage_d_event_redirige", workspace=workspace_id, scope=scope, name=name)
        return replace(declared, parents=parents), commit

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
            await self._check_against_branch(copy, declared, existing)
            kept = [
                declared if d.name == declared.name else d for d in _own(existing, declared.scope)
            ]
            declared = await _with_parents(copy, declared)
            if kept == _own(existing, declared.scope):
                return declared, None
            commit = await self._rewrite(copy, author, declared.scope, kept)
        await self._event(workspace_id, REPLACED_EVENT, author, declared, commit, copy.branch)
        log.info(
            "type_d_event_modifie", workspace=workspace_id, scope=declared.scope, name=declared.name
        )
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
        log.info("type_d_event_supprime", workspace=workspace_id, scope=scope, name=name)
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

    async def _check_against_branch(
        self, copy: WorkCopy, declared: DeclaredType, existing: list[DeclaredType]
    ) -> None:
        """Ce qui ne se vérifie qu'avec la branche sous les yeux : domaine, modèle, clés."""
        await self._check_declaration(copy, declared, existing)
        text = await copy.read(declared.model_path)
        if text is None:
            raise EventModelError([Problem("model", "modele_inconnu", declared.model_path)])
        problems = await self._model_problems(copy, declared, text)
        if problems:
            raise EventModelError(problems)

    async def _check_declaration(
        self, copy: WorkCopy, declared: DeclaredType, existing: list[DeclaredType]
    ) -> None:
        """Ce qui vaut de la DÉCLARATION seule : son domaine, et son nom dans le workspace."""
        if declared.scope != SHARED and declared.scope not in domains_in(await copy.paths()):
            # Le domaine se déclare à part, comme pour un modèle : le créer ici au passage
            # ferait d'une faute de frappe un domaine de plus, sans que personne ne le voie.
            raise WorkspaceConflictError("domaine_inconnu")
        # Un nom unique dans TOUT le workspace, et non dans le seul périmètre : un script
        # qui `INCLUDE` deux artefacts déclarant le même nom ne charge pas du tout — le
        # moteur lève « event 'a' is already declared » pendant la visite (mesuré le
        # 14/11/2026). Refuser ici, c'est refuser au geste plutôt qu'au chargement.
        if any(d.name == declared.name and d.scope != declared.scope for d in existing):
            raise WorkspaceConflictError("nom_pris_ailleurs")

    def _parent_model(
        self,
        declared: DeclaredType,
        existing: list[DeclaredType],
        parent: tuple[str, str] | None,
    ) -> tuple[str, str] | None:
        """Le modèle dont le payload héritera : celui du type d'event parent, ou None.

        Le parent est un type d'event DÉJÀ déclaré sur la branche — « redirigé sur un
        autre event présent sur le disque ». Un modèle quelconque ne peut pas l'être : ce
        serait un héritage dont l'écran ne saurait pas dire de quel event il vient.

        `None` est l'event de base, et il n'a pas de modèle : le moteur applique sa racine
        d'office à tout payload (décision 2 du 22/11/2026).
        """
        if parent is None:
            return None
        parent_scope, parent_name = checked_scope(parent[0]), checked_name(parent[1])
        found = [d for d in existing if (d.scope, d.name) == (parent_scope, parent_name)]
        if not found:
            raise EventTypeNotFoundError(parent_name)
        if not visible(declared.scope, found[0].model):
            # Hériter d'un event d'un autre domaine ferait designer par l'artefact d'un
            # périmètre un modèle qu'il ne voit pas : le moteur chargerait un schéma
            # absent de son registre. Même règle que les modèles entre eux.
            raise WorkspaceConflictError("portee_du_modele")
        return found[0].model

    async def _check_model(
        self,
        copy: WorkCopy,
        declared: DeclaredType,
        content: str,
        parent_model: tuple[str, str] | None,
    ) -> None:
        """Refuse AVANT d'écrire : le cycle d'abord, puis ce que le payload composé exige."""
        if parent_model is not None:
            cycles = await cycle_problems(copy.read, declared.model, parent_model)
            if cycles:
                # Le cycle d'abord : une ascendance qui boucle ne se parcourt pas, donc
                # les règles du payload composé ne diraient rien de sûr tant qu'il est là.
                raise EventModelError(cycles)
        problems = await self._model_problems(copy, declared, content)
        if problems:
            raise EventModelError(problems)

    async def _model_problems(
        self, copy: WorkCopy, declared: DeclaredType, text: str
    ) -> list[Problem]:
        """Ce qui empêche CE texte de porter le payload — le sien, et celui de ses parents.

        Prend le texte plutôt que de le lire : à la création, le modèle n'est pas encore
        dans la copie, et il ne doit pas y être avant que tout soit accepté (la copie de
        travail persiste, et une copie à moitié écrite serait committée par le geste
        suivant — c'est la règle de `datamodels.writing`).
        """
        schema = parse_schema(text)
        above = await ancestry(copy.read, parents_of(text))
        if above is None:
            # Plus profond que la borne : on ne connaît pas l'ascendance, donc on ne peut
            # affirmer ni que les clés désignent quelque chose, ni qu'aucun parent ne ferme
            # le schéma. Mesuré : le moteur, lui, part en `RecursionError`.
            return [Problem("allOf", TOO_DEEP, str(MAX_DEPTH))]
        return (
            payload_problems(text, schema)
            + loop_problems(declared.model, above)
            + list(above.problems)
            + dedup_problems(declared.unique, schema, above.properties)
        )

    async def _rewrite(
        self, copy: WorkCopy, author: EventAuthor, scope: str, types: list[DeclaredType]
    ) -> str:
        """Édite l'artefact d'un périmètre, ou le supprime quand il ne reste RIEN à déclarer.

        Édite, et ne réécrit pas : jusqu'au 17/11/2026 le texte était rendu depuis la
        seule liste des types d'event, donc tout `DEFINE RULE`, `ACTION`, `ARTIFACT`,
        `CONST` et le `DESCRIPTION` du fichier disparaissaient sans un mot au premier
        geste (bug `ff8779c6`). `artefact.rewrite` ne remplace que les étendues des types
        d'event, situées par le parseur du moteur.

        Un artefact sans aucune déclaration est une erreur de syntaxe pour le moteur : le
        laisser derrière, vide, ferait échouer le chargement de tout le répertoire. On
        retire donc le fichier — mais seulement s'il ne reste plus rien, règles comprises.
        """
        path = fragment_path(scope)
        current = await copy.read(path)
        text = rewrite(
            current, scope, [EventType(d.name, d.label, d.model, d.unique) for d in types]
        )
        if text:
            await copy.write(path, text)
        elif current is not None:
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

    @property
    def _journal(self) -> ModelJournal:
        """Le journal des faits de MODÈLE, celui de `DataModelsService`.

        Créer un type d'event écrit aussi un modèle, et rediriger son héritage n'écrit QUE
        lui : ces faits-là sont des faits de modèle, et leur donner une forme d'event à
        part aurait fait deux vocabulaires pour un seul fichier changé.
        """
        return ModelJournal(self.pool, self.catalog, self.now)


def _own(declared: list[DeclaredType], scope: str) -> list[DeclaredType]:
    return [d for d in declared if d.scope == scope]


async def _with_parents(copy: WorkCopy, declared: DeclaredType) -> DeclaredType:
    """La même déclaration, portant l'héritage que son modèle écrit.

    Rendu par les gestes et pas seulement par la lecture : l'écran affiche l'héritage sous
    l'event, et il le réaffiche depuis la réponse du geste — sans cela, une déclaration
    faite sur un modèle qui hérite déjà s'afficherait « hérite de l'event de base ».
    """
    return replace(declared, parents=parents_of(await copy.read(declared.model_path) or ""))


async def _declared(copy: WorkCopy) -> list[DeclaredType]:
    """Tous les types déclarés sur la branche, ou rien : la règle du tout-ou-rien."""
    return declared_in(await read_perimeters(copy.read, await copy.paths()))
