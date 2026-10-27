from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.workshop.domains import DOMAINS, checked_domain, domains_in
from miles.workshop.target import Gesture, WorkBranches
from miles.workspaces.model import WorkspaceInputError

log = structlog.get_logger(__name__)

CREATED_EVENT = "domain.created"
EVENT_TYPES = frozenset({CREATED_EVENT})
# git ne garde pas un répertoire vide : un domaine sans élément tient par ce fichier.
_PLACEHOLDER = ".gitkeep"


def domain_name(name: str) -> str:
    try:
        return checked_domain(name)
    except ValueError:
        # Le nom devient un segment de chemin : refusé avant tout accès au dépôt.
        raise WorkspaceInputError("name") from None


@dataclass(frozen=True)
class DomainsService:
    """Domaines d'une branche (story 7fa00f56) : les répertoires de `domains/`.

    On les déclare ici pour qu'un modèle ne crée plus son domaine au passage, où une
    faute de frappe en faisait naître un nouveau sans que personne ne le voie.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[str]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return domains_in(await copy.paths())

    async def resolve_add(
        self, author: EventAuthor, workspace_id: str, name: str, *, branch: str | None = None
    ) -> str | None:
        """Ajoute le domaine ; s'il existe déjà : sans effet, None."""
        name = domain_name(name)
        path = f"{DOMAINS}{name}/{_PLACEHOLDER}"
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if name in domains_in(await copy.paths()):
                return None
            await copy.write(path, "")
            commit = await self.branches.commit(copy, f"Domaine {name}", author)
        event = NewEvent(
            CREATED_EVENT,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"domain": name, "commit": commit, "branch": copy.branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
        log.info("domaine_ajoute", workspace=workspace_id, domain=name)
        return commit
