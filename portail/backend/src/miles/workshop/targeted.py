from __future__ import annotations

from dataclasses import dataclass

from miles_socle.events.model import EventAuthor

from miles.contracts.derived import present_models
from miles.contracts.layout import checked_slug, slugs_in
from miles.contracts.reading import Contract, contract_at
from miles.workshop.domains import (
    MAX_CONTENT_BYTES,
    DomainContent,
    DomainNotFoundError,
    Element,
    checked_domain,
    domain_files,
    domains_in,
    section_of,
    shared_messages,
)
from miles.workshop.reading import Read, branch_source
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceInputError


class ContractUnknownError(Exception):
    """Contrat absent de la branche : on nomme ceux qui existent."""

    def __init__(self, slug: str, existing: list[str]) -> None:
        super().__init__(slug)
        self.slug, self.existing = slug, existing


@dataclass(frozen=True)
class Page:
    """Des éléments lus sous la borne de taille ; au-delà, leur chemin seul."""

    elements: list[Element]
    truncated: bool
    next_after: str | None


async def read_page(read: Read, paths: list[str], after: str | None) -> Page:
    """Lit dans l'ordre des chemins, après `after`, jusqu'à la borne (critère 11).

    Au moins un élément est toujours rendu entier : un fichier plus gros que la borne
    ne bloquerait sinon jamais la suite.
    """
    elements: list[Element] = []
    budget = MAX_CONTENT_BYTES
    last: str | None = None
    for path in (p for p in paths if after is None or p > after):
        if budget <= 0:
            elements.append(Element(path, None))
            continue
        content = await read(path)
        budget -= len((content or "").encode())
        elements.append(Element(path, content))
        last = path
    truncated = any(e.content is None for e in elements)
    return Page(elements, truncated, last if truncated else None)


@dataclass(frozen=True)
class TargetedReads:
    """Lectures ciblées pour un agent (story 1d8396a3) : un domaine d'un coup, un contrat
    et ses versions, les messages transverses — sans parcourir le dépôt."""

    branches: WorkBranches

    async def resolve_domains(
        self, viewer: EventAuthor, workspace_id: str, branch: str | None, commit: str | None
    ) -> tuple[str, list[str]]:
        async with branch_source(self.branches, viewer, workspace_id, branch, commit) as source:
            return source.commit, domains_in(await source.paths())

    async def resolve_domain(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        name: str,
        branch: str | None,
        commit: str | None,
        after: str | None,
    ) -> tuple[str, DomainContent]:
        try:
            name = checked_domain(name)
        except ValueError:
            raise WorkspaceInputError("domaine") from None
        async with branch_source(self.branches, viewer, workspace_id, branch, commit) as source:
            paths = await source.paths()
            existing = domains_in(paths)
            if name not in existing:
                raise DomainNotFoundError(name, existing)
            page = await read_page(source.read, domain_files(paths, name), after)
        content = DomainContent(name, truncated=page.truncated, next_after=page.next_after)
        prefix = f"domains/{name}/"
        for element in page.elements:
            section = section_of(element.path.removeprefix(prefix))
            target = content.misplaced if section is None else content.sections[section]
            target.append(element)
        return source.commit, content

    async def resolve_shared_messages(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        branch: str | None,
        commit: str | None,
        after: str | None,
    ) -> tuple[str, Page]:
        async with branch_source(self.branches, viewer, workspace_id, branch, commit) as source:
            page = await read_page(source.read, shared_messages(await source.paths()), after)
            return source.commit, page

    async def resolve_contracts(
        self, viewer: EventAuthor, workspace_id: str, branch: str | None, commit: str | None
    ) -> tuple[str, list[Contract]]:
        async with branch_source(self.branches, viewer, workspace_id, branch, commit) as source:
            paths = await source.paths()
            found = [await contract_at(source.read, paths, s) for s in slugs_in(paths)]
            return source.commit, [c for c in found if c is not None]

    async def resolve_contract(
        self,
        viewer: EventAuthor,
        workspace_id: str,
        slug: str,
        branch: str | None,
        commit: str | None,
        version: int | None = None,
        after: str | None = None,
    ) -> tuple[str, Contract, Page | None]:
        """Le contrat ; avec `version`, aussi les modèles dérivés de cette version (story
        47f55d8b), bornés comme un domaine."""
        slug = checked_slug(slug)
        async with branch_source(self.branches, viewer, workspace_id, branch, commit) as source:
            paths = await source.paths()
            contract = await contract_at(source.read, paths, slug)
            if contract is None:
                raise ContractUnknownError(slug, slugs_in(paths))
            models = None
            if version is not None:
                files = sorted(present_models(paths, slug, version).values())
                models = await read_page(source.read, files, after)
            return source.commit, contract, models
