"""Les gestes du portail sur les modèles de données : un geste, une branche, un fait.

Ce module n'est QUE cet enchaînement — ouvrir la branche pour le bon geste, appeler la
marche qui lit ou qui écrit, puis journaliser ce qui a été poussé. Les marches vivent à
côté : `reading` pour ce qu'un modèle est, `writing` pour ce qui s'écrit et ce qui se
refuse, `links` pour ses renvois dans les deux sens, `events` pour ce que le journal
retient (découpage de l'enabler `e585121e`, à comportement constant).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
from miles_socle.events.catalog import EventCatalog
from miles_socle.events.model import EventAuthor
from miles_socle.parametrage.example import example_of

from miles.datamodels.errors import ModelInUseError, ModelNotFoundError
from miles.datamodels.events import (
    CREATED_EVENT,
    DELETED_EVENT,
    REPLACED_EVENT,
    ModelJournal,
)
from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import ModelEntry, checked_name, checked_scope, model_path
from miles.datamodels.links import users
from miles.datamodels.meta import meta_path
from miles.datamodels.patch import patched as _patched
from miles.datamodels.paths import PathEntry, paths_of
from miles.datamodels.reading import described, entries, entries_in, inlined_schema
from miles.datamodels.schema import ModelSchema, draft, normalized, parse_schema
from miles.datamodels.usages import Listing, read_listing
from miles.datamodels.writing import write_new, write_replacement
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import checked_label


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
    ) -> Listing:
        """Les modèles de la branche, chacun avec ce qui le DÉSIGNE (story e36192f8).

        Les usages voyagent avec la liste, et non par une route à eux : ils se lisent dans
        la MÊME copie, dont les fichiers de modèle sont déjà lus pour leur label. Une route
        dédiée aurait rouvert la branche pour une page qui est sur le chemin critique
        mesuré de l'enabler 7fb3577c — et rendu deux instantanés de deux commits possibles
        là où l'écran en montre un seul.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            paths = await copy.paths()
            # Le texte de chaque modèle, lu UNE fois : son label en sort, et ses `$ref`
            # aussi. Deux boucles séparées auraient lu deux fois chaque fichier.
            texts = [(e, await copy.read(e.path) or "") for e in entries_in(paths)]
            return await read_listing(
                copy.read, paths, [(await described(copy, e, text), text) for e, text in texts]
            )

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
            return await described(copy, entry), content

    async def resolve_example(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> Any:
        """Le gabarit JSON de ce modèle : la forme à produire, renvois résolus.

        Sert le bouton « remplir depuis le modèle de destination ».
        """
        return example_of(await self._inlined(viewer, workspace_id, scope, name, branch))

    async def resolve_paths(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        *,
        branch: str | None = None,
    ) -> list[PathEntry]:
        """Les chemins du modèle, pour l'intellisense de l'éditeur JSLT."""
        return paths_of(await self._inlined(viewer, workspace_id, scope, name, branch))

    async def _inlined(
        self, viewer: EventAuthor, workspace_id: str, scope: str, name: str, branch: str | None
    ) -> Any:
        """Le schéma du modèle, renvois résolus, en UNE ouverture de branche.

        Les deux lectures ci-dessus demandent la même chose, et pour la même raison : sans
        la résolution, un modèle qui en désigne un autre rendrait un trou là où l'on
        attend sa forme, et n'offrirait aucun chemin sous ce renvoi. Un seul clone : les
        modèles désignés se lisent dans la même copie.
        """
        scope, name = checked_scope(scope), checked_name(name)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(entry.path)
            if content is None:
                raise ModelNotFoundError(entry.path)
            return await inlined_schema(copy, load_yaml(content), (scope, name))

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

    async def _create(
        self,
        author: EventAuthor,
        workspace_id: str,
        scope: str,
        name: str,
        content: str,
        branch: str | None,
    ) -> tuple[ModelEntry, str | None]:
        schema: ModelSchema = parse_schema(content)
        entry = ModelEntry(scope, name, model_path(scope, name))
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            entry, commit = await write_new(copy, self.branches, author, entry, content, schema)
        if commit is None:
            return entry, None
        await self._journal.db_write(
            workspace_id, CREATED_EVENT, author, entry, commit, copy.branch
        )
        return entry, commit

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
            entry, commit = await write_replacement(
                copy, self.branches, author, scope, name, content
            )
        if commit is None:
            return entry, None
        await self._journal.db_write(
            workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch
        )
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
            entry, commit = await write_replacement(
                copy, self.branches, author, scope, name, _patched(text, apply)
            )
        if commit is None:
            return entry, None
        await self._journal.db_write(
            workspace_id, REPLACED_EVENT, author, entry, commit, copy.branch
        )
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
            if entry not in await entries(copy):
                raise ModelNotFoundError(entry.path)
            designating = await users(copy, entry)
            if designating:
                raise ModelInUseError(designating)
            await copy.remove(entry.path)
            if await copy.read(meta_path(entry.path)) is not None:
                await copy.remove(meta_path(entry.path))
            commit = await self.branches.commit(copy, f"Suppression du modèle {entry.path}", author)
        await self._journal.db_write(
            workspace_id, DELETED_EVENT, author, entry, commit, copy.branch
        )
        return commit

    @property
    def _journal(self) -> ModelJournal:
        return ModelJournal(self.pool, self.catalog, self.now)
