from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.contracts.layout import (
    DIRECTIONS,
    ContractMeta,
    checked_slug,
    meta_path,
    meta_text,
    read_meta,
    slugs_in,
    version_path,
    versions_in,
)
from miles.contracts.openapi import ParsedContract, parse_contract
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceInputError, checked_label

log = structlog.get_logger(__name__)

DECLARED_EVENT = "contract.declared"
VERSION_EVENT = "contract.version_imported"
EVENT_TYPES = frozenset({DECLARED_EVENT, VERSION_EVENT})


@dataclass(frozen=True)
class ContractVersion:
    number: int
    # None : retouché hors de Miles et devenu illisible. Listé quand même, la validation
    # de la branche dira pourquoi.
    parsed: ParsedContract | None


@dataclass(frozen=True)
class Contract:
    meta: ContractMeta
    versions: tuple[ContractVersion, ...]


class ContractNotFoundError(Exception):
    pass


class ContractTakenError(Exception):
    """Slug déjà occupé : on nomme le contrat qui l'occupe."""

    def __init__(self, occupant: str) -> None:
        super().__init__(f"slug occupé par {occupant}")
        self.occupant = occupant


@dataclass(frozen=True)
class ContractsService:
    """Contrats OpenAPI de la branche de travail (story 502b24c2, revu le 22/10/2026).

    Deux gestes : déclarer le contrat (label, slug, sens — figés), puis y intégrer les
    fichiers du tiers, chacun en version qui coexiste avec les précédentes. Importés,
    jamais édités : aucun chemin de renommage, même pour un administrateur.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    @staticmethod
    def resolve_preview(content: str) -> ParsedContract:
        """Lecture du fichier sans rien écrire : l'écran la montre avant l'intégration."""
        return parse_contract(content)

    async def resolve_list(self, workspace_id: str, *, branch: str | None = None) -> list[Contract]:
        async with self.branches.checkout(workspace_id, branch) as copy:
            paths = await copy.paths()
            found = [await _contract(copy, paths, slug) for slug in slugs_in(paths)]
        return [c for c in found if c is not None]

    async def resolve_get(
        self, workspace_id: str, slug: str, *, branch: str | None = None
    ) -> Contract:
        slug = checked_slug(slug)
        async with self.branches.checkout(workspace_id, branch) as copy:
            contract = await _contract(copy, await copy.paths(), slug)
        if contract is None:
            raise ContractNotFoundError(slug)
        return contract

    async def resolve_declare(
        self,
        author: EventAuthor,
        workspace_id: str,
        label: str,
        slug: str,
        direction: str,
        *,
        branch: str | None = None,
    ) -> tuple[Contract, bool]:
        """Déclare le contrat, sans fichier ; rend (contrat, déjà_là).

        Rejeu à l'identique : sans effet. Le fichier vient ensuite, par `resolve_import`.
        """
        meta = ContractMeta(checked_slug(slug), checked_label(label), _direction(direction))
        async with self.branches.checkout(workspace_id, branch) as copy:
            paths = await copy.paths()
            existing = await _contract(copy, paths, meta.slug)
            if existing is not None:
                if existing.meta == meta:
                    return existing, True
                raise ContractTakenError(existing.meta.label)
            # Un dossier sans déclaration lisible (retouché hors de Miles) occupe aussi le slug.
            if versions_in(paths, meta.slug):
                raise ContractTakenError(meta.slug)
            await copy.write(meta_path(meta.slug), meta_text(meta))
            commit = await self.branches.push(copy, f"Déclaration du contrat {meta.slug}", author)
        await self._journal(
            DECLARED_EVENT,
            workspace_id,
            author,
            {"slug": meta.slug, "sens": meta.direction, "commit": commit, "branch": copy.branch},
        )
        log.info("contrat_declare", workspace=workspace_id, slug=meta.slug, sens=meta.direction)
        return Contract(meta, ()), False

    async def resolve_import(
        self,
        author: EventAuthor,
        workspace_id: str,
        slug: str,
        content: str,
        *,
        branch: str | None = None,
    ) -> tuple[ContractVersion, bool]:
        """Intègre un fichier en version suivante ; rend (version, déjà_là)."""
        slug = checked_slug(slug)
        # Vérifié avant tout accès au dépôt : un fichier refusé ne coûte aucun clone.
        parsed = parse_contract(content)
        async with self.branches.checkout(workspace_id, branch) as copy:
            paths = await copy.paths()
            if read_meta(await copy.read(meta_path(slug))) is None:
                raise ContractNotFoundError(slug)
            numbers = versions_in(paths, slug)
            # Un fichier déjà intégré à l'identique ne crée pas de version : le rejeu d'un
            # import ne doit pas fabriquer v2, v3… du même contrat.
            for number in numbers:
                if await copy.read(version_path(slug, number)) == content:
                    return ContractVersion(number, parsed), True
            number = (numbers[-1] if numbers else 0) + 1
            await copy.write(version_path(slug, number), content)
            message = f"Intégration du contrat {slug} (v{number})"
            commit = await self.branches.push(copy, message, author)
        properties = {"slug": slug, "version": number, "commit": commit, "branch": copy.branch}
        await self._journal(VERSION_EVENT, workspace_id, author, properties)
        log.info("contrat_integre", workspace=workspace_id, slug=slug, version=number)
        return ContractVersion(number, parsed), False

    async def _journal(
        self, kind: str, workspace_id: str, author: EventAuthor, properties: dict[str, object]
    ) -> None:
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _direction(direction: str) -> str:
    if direction not in DIRECTIONS:
        raise WorkspaceInputError("sens")
    return direction


async def _contract(copy: WorkCopy, paths: list[str], slug: str) -> Contract | None:
    meta = read_meta(await copy.read(meta_path(slug)))
    if meta is None:
        return None
    versions = []
    for number in versions_in(paths, slug):
        try:
            parsed: ParsedContract | None = parse_contract(
                await copy.read(version_path(slug, number)) or ""
            )
        except ValueError:
            parsed = None
        versions.append(ContractVersion(number, parsed))
    return Contract(meta, tuple(versions))
