from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from miles.contracts.history import Comparison, compare
from miles.contracts.openapi import ParsedContract
from miles.contracts.reading import Contract, ContractVersion

# Formes échangées par les routes des contrats, et leur calcul depuis un contrat lu.
NO_OPERATION = "aucune_operation"


class OperationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str
    path: str
    operation_id: str | None


class FetchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class FetchOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    openapi: str
    operations: list[OperationOut]
    # Licite mais probablement le mauvais fichier : signalé, pas refusé.
    warnings: list[str]
    # Les modèles que l'intégration écrira, un par schéma (story 47f55d8b).
    models: list[str]


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    # None : fichier retouché hors de Miles et devenu illisible.
    title: str | None
    operations: int
    warnings: list[str]
    # None : version déposée hors de Miles, sans date ni auteur connus.
    imported_at: datetime | None
    imported_by: str | None
    # Modèles dérivés présents dans git (story 47f55d8b), et leur état face au fichier :
    # « a_jour », « a_rederiver » ou « non_derivable » ; None si le fichier est illisible.
    models: list[str]
    models_state: str | None


class VersionOperationOut(OperationOut):
    # « nouvelle » : absente de la version précédente. None : déjà là, ou rien à comparer.
    change: str | None


class VersionDetailOut(VersionOut):
    operation_list: list[VersionOperationOut]
    # Version à laquelle celle-ci est comparée ; None pour la première.
    compared_with: int | None
    removed: list[OperationOut]


class ContractOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    sens: str
    versions: list[VersionOut]


class ContractDetailOut(ContractOut):
    versions: list[VersionDetailOut]  # type: ignore[assignment]


class DerivedModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    path: str
    # Le YAML tel qu'il est dans git : un modèle dérivé se lit, il ne s'édite pas.
    content: str


class ContractDeclare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    slug: str
    # Pas de défaut : None se refuse en nommant le champ, comme une valeur hors liste.
    sens: str | None = None


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class ContractChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str | None = None
    sens: str | None = None
    label: str | None = None


def operations_out(parsed: ParsedContract | None) -> list[OperationOut]:
    operations = parsed.operations if parsed is not None else ()
    return [
        OperationOut(method=o.method, path=o.path, operation_id=o.operation_id) for o in operations
    ]


def version_warnings(count: int) -> list[str]:
    return [NO_OPERATION] if count == 0 else []


def versions_out(contract: Contract) -> list[VersionDetailOut]:
    details, previous = [], None
    for version in contract.versions:
        details.append(version_out(contract, version, compare(previous, version.parsed)))
        previous = (version.number, version.parsed)
    return details


def version_out(
    contract: Contract, version: ContractVersion, comparison: Comparison
) -> VersionDetailOut:
    operations = version.parsed.operations if version.parsed is not None else ()
    deposit = contract.meta.imported(version.number)
    return VersionDetailOut(
        number=version.number,
        title=version.parsed.title if version.parsed is not None else None,
        operations=len(operations),
        warnings=version_warnings(len(operations)),
        imported_at=datetime.fromisoformat(deposit.imported_at) if deposit else None,
        imported_by=deposit.by if deposit else None,
        models=list(version.models.present) if version.models else [],
        models_state=version.models.state if version.models else None,
        operation_list=[
            VersionOperationOut(
                method=o.method,
                path=o.path,
                operation_id=o.operation_id,
                change="nouvelle" if (o.method, o.path) in comparison.added else None,
            )
            for o in operations
        ],
        compared_with=comparison.previous,
        removed=[
            OperationOut(method=o.method, path=o.path, operation_id=o.operation_id)
            for o in comparison.removed
        ],
    )


def contract_out(contract: Contract) -> ContractOut:
    summary = {"operation_list", "compared_with", "removed"}
    versions = [VersionOut(**v.model_dump(exclude=summary)) for v in versions_out(contract)]
    meta = contract.meta
    return ContractOut(slug=meta.slug, label=meta.label, sens=meta.direction, versions=versions)
