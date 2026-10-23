from __future__ import annotations

from dataclasses import dataclass

from miles.contracts.derived import DerivedState, derived_state
from miles.contracts.layout import ContractMeta, meta_path, read_meta, version_path, versions_in
from miles.contracts.openapi import ParsedContract, parse_contract
from miles.workshop.reading import Read


@dataclass(frozen=True)
class ContractVersion:
    number: int
    # None : retouché hors de Miles et devenu illisible. Listé quand même, la validation
    # de la branche dira pourquoi.
    parsed: ParsedContract | None
    # Ses modèles dérivés dans git (story 47f55d8b) ; None si le fichier est illisible.
    models: DerivedState | None = None


@dataclass(frozen=True)
class Contract:
    meta: ContractMeta
    versions: tuple[ContractVersion, ...]


async def contract_at(read: Read, paths: list[str], slug: str) -> Contract | None:
    """Le contrat `slug` tel que le montrent `paths` et `read` : tête ou commit passé."""
    meta = read_meta(await read(meta_path(slug)))
    if meta is None:
        return None
    versions = []
    for number in versions_in(paths, slug):
        try:
            parsed: ParsedContract | None = parse_contract(
                await read(version_path(slug, number)) or ""
            )
        except ValueError:
            # Retouché hors de Miles et devenu illisible : listé quand même, la validation
            # de la branche dira pourquoi.
            parsed = None
        models = (
            await derived_state(read, paths, slug, number, parsed.document)
            if parsed is not None
            else None
        )
        versions.append(ContractVersion(number, parsed, models))
    return Contract(meta, tuple(versions))
