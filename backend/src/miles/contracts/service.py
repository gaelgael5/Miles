from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog

from miles.contracts.openapi import SLUG_RE, ParsedContract, parse_contract, propose_slug
from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.git.workcopy import WorkCopy
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceInputError

log = structlog.get_logger(__name__)

IMPORTED_EVENT = "contract.imported"
EVENT_TYPES = frozenset({IMPORTED_EVENT})
# Sortant : appel d'un service distant ; entrant : webhook reçu. Pas de valeur par
# défaut : un webhook pris pour un appel sortant produirait un mapping à l'envers.
DIRECTIONS = frozenset({"sortant", "entrant"})
# Les contrats vivent hors domaine, à la racine : leur frontière est le système tiers.
# Le sens se range à côté de la version, dans un fichier du contrat (latitude du ticket).
_META = "contract.yaml"
_FIRST = "v1.yaml"
_DIR_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/" + re.escape(_META) + "$")


@dataclass(frozen=True)
class ContractEntry:
    slug: str
    direction: str
    title: str
    operations: int


class ContractNotFoundError(Exception):
    pass


class ContractTakenError(Exception):
    """Slug déjà occupé : on nomme le contrat qui l'occupe (critère 4)."""

    def __init__(self, occupant: str) -> None:
        super().__init__(f"slug occupé par {occupant}")
        self.occupant = occupant


def contract_dir(slug: str) -> str:
    return f"contracts/{slug}"


def read_meta(text: str | None) -> tuple[str, str] | None:
    """(slug, sens) du fichier de métadonnées, ou None s'il est absent ou illisible."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict):
        return None
    slug, direction = data.get("slug"), data.get("sens")
    if not isinstance(slug, str) or direction not in DIRECTIONS:
        return None
    return slug, str(direction)


def meta_text(slug: str, direction: str) -> str:
    # Valeurs déjà validées (slug par regex, sens dans une liste fermée) : aucune n'a
    # besoin d'échappement YAML.
    return f"slug: {slug}\nsens: {direction}\n"


@dataclass(frozen=True)
class ContractsService:
    """Contrats OpenAPI importés dans la branche de travail (story 502b24c2).

    Importés, jamais édités : le contrat est la propriété du tiers. Le slug est figé à la
    création ; il n'existe aucun chemin de renommage, même pour un administrateur.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    @staticmethod
    def resolve_preview(content: str) -> tuple[str, ParsedContract]:
        """Slug proposé et lecture du contrat, sans rien écrire : l'écran le montre avant."""
        parsed = parse_contract(content)
        return propose_slug(parsed.title), parsed

    async def resolve_list(self, workspace_id: str) -> list[ContractEntry]:
        async with self.branches.checkout(workspace_id) as copy:
            entries = []
            for path in await copy.paths():
                match = _DIR_RE.match(path)
                if match is not None:
                    entry = await _entry(copy, match["slug"])
                    if entry is not None:
                        entries.append(entry)
            return entries

    async def resolve_get(
        self, workspace_id: str, slug: str
    ) -> tuple[ContractEntry, ParsedContract]:
        _slug(slug)
        async with self.branches.checkout(workspace_id) as copy:
            meta = read_meta(await copy.read(f"{contract_dir(slug)}/{_META}"))
            content = await copy.read(f"{contract_dir(slug)}/{_FIRST}")
        if meta is None or content is None:
            raise ContractNotFoundError(slug)
        parsed = parse_contract(content)
        return ContractEntry(slug, meta[1], parsed.title, len(parsed.operations)), parsed

    async def resolve_create(
        self, author: EventAuthor, workspace_id: str, slug: str, direction: str, content: str
    ) -> tuple[ContractEntry, ParsedContract, bool]:
        """Importe la v1 ; rend (contrat, lecture, déjà_là). Même fichier et slug : sans effet."""
        if direction not in DIRECTIONS:
            raise WorkspaceInputError("sens")
        slug = _slug(slug)
        # Vérifié avant tout accès au dépôt : un fichier refusé ne coûte aucun clone.
        parsed = parse_contract(content)
        entry = ContractEntry(slug, direction, parsed.title, len(parsed.operations))
        base = contract_dir(slug)
        async with self.branches.checkout(workspace_id) as copy:
            meta = read_meta(await copy.read(f"{base}/{_META}"))
            existing = await copy.read(f"{base}/{_FIRST}")
            if meta is not None or existing is not None:
                if meta == (slug, direction) and existing == content:
                    return entry, parsed, True
                occupant = await _entry(copy, slug)
                raise ContractTakenError(occupant.title if occupant else slug)
            await copy.write(f"{base}/{_META}", meta_text(slug, direction))
            await copy.write(f"{base}/{_FIRST}", content)
            commit = await self.branches.push(copy, f"Import du contrat {slug} (v1)", author)
        properties = {"slug": slug, "sens": direction, "commit": commit}
        event = NewEvent(
            IMPORTED_EVENT, (ObjectRef("workspace", workspace_id),), author, properties
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
        log.info("contrat_importe", workspace=workspace_id, slug=slug, sens=direction)
        return entry, parsed, False


async def _entry(copy: WorkCopy, slug: str) -> ContractEntry | None:
    meta = read_meta(await copy.read(f"{contract_dir(slug)}/{_META}"))
    content = await copy.read(f"{contract_dir(slug)}/{_FIRST}")
    if meta is None or content is None:
        return None
    try:
        parsed = parse_contract(content)
    except ValueError:
        # Retouché hors de Miles et devenu illisible : listé quand même, la validation
        # de la branche dira pourquoi.
        return ContractEntry(slug, meta[1], slug, 0)
    return ContractEntry(slug, meta[1], parsed.title, len(parsed.operations))


def _slug(slug: str) -> str:
    # Vide : la normalisation du titre n'a rien laissé, on demande un slug explicite
    # plutôt que d'en inventer un (critère 5).
    slug = slug.strip()
    if not slug:
        raise WorkspaceInputError("slug", "vide")
    if not SLUG_RE.match(slug):
        raise WorkspaceInputError("slug")
    return slug
