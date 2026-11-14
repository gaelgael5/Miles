from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.catalog import EventCatalog, EventShape, closed_block
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef
from miles_socle.parametrage.example import example_of
from miles_socle.parametrage.refs import inline_refs

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml
from miles.datamodels.layout import (
    SHARED,
    ModelEntry,
    checked_name,
    checked_scope,
    entry_of,
    model_path,
    visible,
)
from miles.datamodels.meta import meta_path, meta_text, read_version
from miles.datamodels.patch import patched as _patched
from miles.datamodels.paths import PathEntry, paths_of
from miles.datamodels.schema import (
    ModelSchema,
    draft,
    normalized,
    parse_schema,
    references_in,
)
from miles.event_shapes import GESTURE, NAME
from miles.git.workcopy import WorkCopy
from miles.workflowevents.dsl import FragmentError, scope_of
from miles.workflowevents.dsl import parse as parse_fragment
from miles.workshop.domains import domains_in
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceConflictError, checked_label

log = structlog.get_logger(__name__)

CREATED_EVENT = "data_model.created"
DELETED_EVENT = "data_model.deleted"
REPLACED_EVENT = "data_model.replaced"
# Le CHEMIN du modèle dans le dépôt, et le geste : les trois faits portent le même bloc,
# parce que la question qu'on leur pose est la même — « quel modèle, et dans quel commit ? ».
_MODELE: dict[str, Any] = {"path": NAME, **GESTURE}
EVENT_SHAPES = (
    EventShape(CREATED_EVENT, "Modèle de données créé", closed_block(_MODELE)),
    EventShape(DELETED_EVENT, "Modèle de données supprimé", closed_block(_MODELE)),
    EventShape(REPLACED_EVENT, "Modèle de données remplacé", closed_block(_MODELE)),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)


class ModelNotFoundError(Exception):
    pass


class ModelInUseError(Exception):
    def __init__(self, users: list[str]) -> None:
        super().__init__(f"référencé par {len(users)} modèle(s)")
        self.users = users


@dataclass(frozen=True)
class DataModelsService:
    """Modèles de données du workspace, écrits dans SA branche de travail (story 266f5ed8).

    Des JSON Schema 2020-12 en YAML depuis le 23/10/2026 (story 0f7cda10).

    Jamais en base, même en cache : le catalogue doit refléter exactement la version git.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[ModelEntry]:
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
    ) -> tuple[ModelEntry, str]:
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise ModelNotFoundError(entry.path)
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
    ) -> tuple[ModelEntry, str | None]:
        """Déclare un modèle par son label et son slug (Gael, 23/10/2026).

        Écrit un schéma objet sans propriété, le label en `title`, et la version 1 ; le
        schéma se complète ensuite à l'édition. Rejeu à l'identique : sans effet, None.
        """
        scope, name, label = checked_scope(scope), checked_name(slug), checked_label(label)
        content = draft(scope, name, label)
        return await self._create(author, workspace_id, scope, name, content, branch)

    async def resolve_example(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> Any:
        """Le gabarit JSON de ce modèle, renvois vers d'autres modèles résolus.

        Sert le bouton « remplir depuis le modèle de destination » : sans la résolution,
        un modèle qui en désigne un autre rendrait un trou là où l'on attend sa forme.
        Un seul clone : les modèles désignés se lisent dans la même copie.
        """
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise ModelNotFoundError(entry.path)
            schema = load_yaml(content)
            inlined = await inlined_schema(copy, schema, (scope, name))
        return example_of(inlined)

    async def resolve_paths(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> list[PathEntry]:
        """Les chemins du modèle, pour l'intellisense de l'éditeur JSLT.

        Mêmes renvois résolus que pour le gabarit, et pour la même raison : un modèle qui
        en désigne un autre n'offrirait sinon aucun chemin sous ce renvoi.
        """
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise ModelNotFoundError(entry.path)
            inlined = await inlined_schema(copy, load_yaml(content), (scope, name))
        return paths_of(inlined)

    async def resolve_create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[ModelEntry, str | None]:
        """Écrit un modèle depuis son schéma ; rejeu du même schéma : sans effet, None."""
        scope, name = checked_scope(scope), checked_name(name)
        # Vérifié avant tout accès au dépôt : un document refusé ne coûte aucun clone.
        parse_schema(content)
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
    ) -> tuple[ModelEntry, str | None]:
        """Remplace le schéma d'un modèle ; même schéma : sans effet, None.

        Le nom ne change pas : c'est le fichier et l'`$id`, que le système réécrit. La
        version monte de 1, tenue par le système (Gael, 23/10/2026).
        """
        scope, name = checked_scope(scope), checked_name(name)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            entry, commit = await self._rewrite(copy, author, scope, name, content)
        if commit is None:
            return entry, None
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_remplace", workspace=workspace_id, path=entry.path)
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
    ) -> tuple[ModelEntry, str | None]:
        """Modifie le schéma par une mutation locale (une propriété), en UN seul passage.

        L'appelant fournit la mutation ; le service lit, applique, puis repart par le MÊME
        chemin qu'un remplacement entier — donc mêmes écarts, même version, même event.
        Un seul `checkout` : lire par `resolve_get` puis écrire par `resolve_replace`
        interrogerait la forge deux fois pour un geste (enabler 782ce1e9).
        """
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            text = await copy.read(entry.path)
            if text is None:
                raise ModelNotFoundError(entry.path)
            entry, commit = await self._rewrite(copy, author, scope, name, _patched(text, apply))
        if commit is None:
            return entry, None
        await self._event(workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_remplace", workspace=workspace_id, path=entry.path)
        return entry, commit

    async def _rewrite(
        self, copy: WorkCopy, author: EventAuthor, scope: str, name: str, content: str
    ) -> tuple[ModelEntry, str | None]:
        """Le coeur d'un remplacement, dans une copie déjà ouverte ; None : rien à écrire."""
        schema = parse_schema(content)
        content = normalized(content, scope, name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        existing = await copy.read(entry.path)
        if existing is None:
            raise ModelNotFoundError(entry.path)
        if existing == content:
            return await _described(copy, entry), None
        await _check_references(copy, entry, schema)
        version = read_version(await copy.read(meta_path(entry.path))) + 1
        await copy.write(entry.path, content)
        await copy.write(meta_path(entry.path), meta_text(version))
        commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
        return await _described(copy, entry), commit

    async def _create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        branch: str | None,
    ) -> tuple[ModelEntry, str | None]:
        schema = parse_schema(content)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            # Le domaine se déclare à part (story 7fa00f56) : le créer ici au passage ferait
            # d'une faute de frappe un domaine de plus, sans que personne ne le voie.
            if scope != SHARED and scope not in domains_in(await copy.paths()):
                raise WorkspaceConflictError("domaine_inconnu")
            existing = await copy.read(entry.path)
            if existing is not None:
                if existing == content:
                    return await _described(copy, entry), None
                raise WorkspaceConflictError("nom_pris")
            await _check_references(copy, entry, schema)
            await copy.write(entry.path, content)
            # Un modèle naît en version 1 : la version est au système, jamais au client.
            await copy.write(meta_path(entry.path), meta_text(1))
            commit = await self.branches.commit(copy, f"Modèle de données {entry.path}", author)
            entry = await _described(copy, entry)
        await self._event(workspace_id, CREATED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_cree", workspace=workspace_id, path=entry.path)
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
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            entries = await _entries(copy)
            if entry not in entries:
                raise ModelNotFoundError(entry.path)
            users = await _users(copy, entry)
            if users:
                raise ModelInUseError(users)
            await copy.remove(entry.path)
            if await copy.read(meta_path(entry.path)) is not None:
                await copy.remove(meta_path(entry.path))
            commit = await self.branches.commit(copy, f"Suppression du modèle {entry.path}", author)
        await self._event(workspace_id, DELETED_EVENT, author, entry, commit, copy.branch)
        log.info("modele_de_donnees_supprime", workspace=workspace_id, path=entry.path)
        return commit

    async def _event(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        entry: ModelEntry,
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


async def _check_references(copy: WorkCopy, entry: ModelEntry, schema: ModelSchema) -> None:
    known = {(e.scope, e.name) for e in await _entries(copy)} | {(entry.scope, entry.name)}
    missing = [
        Problem(where, "modele_inconnu", f"{scope}/{name}")
        for where, (scope, name) in schema.references
        if (scope, name) not in known or not visible(entry, (scope, name))
    ]
    if missing:
        raise ModelGrammarError(missing)


async def _entries(copy: WorkCopy) -> list[ModelEntry]:
    return [e for e in map(entry_of, await copy.paths()) if e is not None]


async def _described(copy: WorkCopy, entry: ModelEntry) -> ModelEntry:
    """Le modèle avec son label (le `title` du schéma) et sa version (ses métadonnées)."""
    text = await copy.read(entry.path)
    try:
        label = parse_schema(text or "").title
    except ValueError:
        # Illisible (retouché hors de Miles) : listé quand même, sans label ; la
        # validation de la branche dira pourquoi.
        label = None
    version = read_version(await copy.read(meta_path(entry.path)))
    return ModelEntry(entry.scope, entry.name, entry.path, label, version or None)


async def _users(copy: WorkCopy, target: ModelEntry) -> list[str]:
    """Documents qui désignent `target` : sa suppression les casserait.

    Deux genres de désignation, et pas un seul : un autre MODÈLE par un `$ref`, et
    l'ARTEFACT d'un périmètre par le `AS @…` d'un `DEFINE EVENT`. Depuis le 14/11/2026,
    c'est le second qui fait d'un modèle un type d'event — sans cette lecture, supprimer
    un modèle laisserait une déclaration qui ne désigne plus rien : la version de la
    branche le refuserait, mais trop tard, après la suppression et depuis un autre écran.
    """
    users = []
    for path in await copy.paths():
        model = entry_of(path)
        if model == target:
            continue
        if model is not None:
            if (target.scope, target.name) in references_in(await copy.read(path) or ""):
                users.append(path)
        elif scope_of(path) is not None and await _declared_in(copy, path, target):
            users.append(path)
    return users


async def _declared_in(copy: WorkCopy, path: str, target: ModelEntry) -> bool:
    """L'artefact d'un périmètre déclare-t-il un type d'event sur `target` ?"""
    try:
        declared = parse_fragment(await copy.read(path) or "")
    except FragmentError:
        # Illisible (retouché hors de Miles) : on ne sait pas ce qu'il désigne, donc on ne
        # bloque pas la suppression sur une supposition. Rien ne se perd pour autant — la
        # validation de la branche refuse de figer une version tant que cet artefact ne se
        # relit pas, et c'est là que le défaut se nomme.
        return False
    return any(d.model == (target.scope, target.name) for d in declared)


async def inlined_schema(copy: WorkCopy, schema: Any, origin: tuple[str, str]) -> Any:
    """Le schéma, renvois vers d'autres modèles remplacés par leur contenu.

    Exposé pour les documents qui partent du dépôt : un `$ref` vers « miles:/… » ne veut
    rien dire hors de Miles — ni pour un visualiseur Swagger, ni pour un appelant.

    La marche est au socle depuis le 02/11/2026 : le module d'environnement doit voir
    le MÊME schéma résolu, sans quoi l'écran proposerait une colonne qu'il refuserait.
    """

    async def read(path: str) -> str | None:
        return await copy.read(path)

    return await inline_refs(read, schema, origin)
