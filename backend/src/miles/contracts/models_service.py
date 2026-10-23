from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.contracts.derived import (
    checked_model_name,
    derive_models,
    models_dir,
    present_models,
)
from miles.contracts.layout import checked_slug, version_path, versions_in
from miles.contracts.openapi import parse_contract
from miles.contracts.service import ContractNotFoundError
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.workshop.target import Gesture, WorkBranches

log = structlog.get_logger(__name__)

REDERIVED_EVENT = "contract.models_rederived"
EVENT_TYPES = frozenset({REDERIVED_EVENT})


@dataclass(frozen=True)
class ContractModelsService:
    """Modèles dérivés des versions de contrat (story 47f55d8b) : lus, redérivés, jamais
    édités. Leur écriture à l'intégration d'une version reste dans `ContractsService`, où
    elle partage le commit du fichier."""

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_model(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        slug: str,
        number: int,
        name: str,
        *,
        branch: str | None = None,
    ) -> tuple[str, str]:
        """(chemin, YAML) d'un modèle dérivé, tel qu'il est dans git : il se lit, ne s'édite pas."""
        slug, name = checked_slug(slug), checked_model_name(name)
        path = f"{models_dir(slug, number)}/{name}.yaml"
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            content = await copy.read(path)
        if content is None:
            raise ContractNotFoundError(path)
        return path, content

    async def resolve_rederive(
        self,
        author: EventAuthor,
        workspace_id: str,
        slug: str,
        number: int,
        *,
        branch: str | None = None,
    ) -> str | None:
        """Réécrit les modèles d'une version d'après son fichier ; déjà à jour : None.

        Pour une version intégrée avant la story 47f55d8b, ou des modèles retouchés à la
        main dans git : le contrat fait foi, jamais le modèle.
        """
        slug = checked_slug(slug)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            paths = await copy.paths()
            if number not in versions_in(paths, slug):
                raise ContractNotFoundError(f"{slug}/v{number}")
            parsed = parse_contract(await copy.read(version_path(slug, number)) or "")
            expected = derive_models(parsed.document, slug, number)
            changed = False
            for path in present_models(paths, slug, number).values():
                if path not in {m.path for m in expected}:
                    await copy.remove(path)
                    changed = True
            for model in expected:
                if await copy.read(model.path) != model.content:
                    await copy.write(model.path, model.content)
                    changed = True
            if not changed:
                return None
            message = f"Modèles du contrat {slug} (v{number}) redérivés"
            commit = await self.branches.commit(copy, message, author)
        properties = {"slug": slug, "version": number, "commit": commit, "branch": copy.branch}
        await self._journal(REDERIVED_EVENT, workspace_id, author, properties)
        log.info("modeles_de_contrat_rederives", workspace=workspace_id, slug=slug, version=number)
        return commit

    async def _journal(
        self, kind: str, workspace_id: str, author: EventAuthor, properties: dict[str, object]
    ) -> None:
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
