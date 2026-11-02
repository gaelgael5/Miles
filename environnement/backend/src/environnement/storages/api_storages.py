"""Les espaces de stockage de cette stack : ce qu'ils sont, et ce qu'ils contiennent.

Lecture seule, comme l'écran de la version servie et pour la même raison : ce qu'un
storage EST vient du paramétrage versionné, et une route qui le changerait ici ferait
exister deux sources pour la même décision. Ce qui s'écrira dans ces tables viendra par
l'ingestion, qui a son propre ticket.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from environnement.storages.ddl import IdentifierError
from environnement.storages.query import (
    PAGE_SIZE,
    FilterError,
    build,
    parse_criterion,
)
from environnement.storages.service import StoragesService

router = APIRouter(prefix="/api/storages")


class ProjectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    # Le chemin tel qu'il est DÉCLARÉ, pour que l'écran montre ce que la personne a choisi
    # dans l'arbre des propriétés, et non le nom de colonne qu'on en a dérivé.
    path: str
    kind: str
    sql_type: str


class IndexOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    columns: list[str]


class StorageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    label: str
    model: str
    schema_name: str
    table_name: str
    keys: list[str]
    projections: list[ProjectionOut]
    indexes: list[IndexOut]
    # Nuls quand le storage est déclaré mais pas encore posé : l'écran doit pouvoir le
    # dire plutôt que de laisser croire à une table vide.
    applied_at: datetime | None
    version_number: int | None
    refusal: str | None
    refusal_detail: str | None


class ObjectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cle: str
    objet: dict[str, Any]
    vu_le: datetime
    modifie_le: datetime
    origine: str
    # Les colonnes projetées, par nom : c'est sur elles que portent les filtres, et les
    # montrer dit pourquoi un objet est dans le résultat.
    columns: dict[str, Any]


class PageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objects: list[ObjectOut]
    total: int
    page: int
    page_size: int


def _service(request: Request) -> StoragesService:
    service: StoragesService = request.app.state.storages
    return service


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("", response_model=list[StorageOut])
async def list_storages(request: Request) -> object:
    """Les storages de la version servie, déclarations et état de leur table ensemble.

    Les deux ensemble et non sur deux routes : l'écran ne sait rien faire d'une
    déclaration sans savoir si elle est posée, et un storage refusé doit apparaître dans
    la MÊME liste — sinon il est invisible, et c'est l'angle mort qu'on veut fermer.
    """
    service = _service(request)
    declared = await service.resolve_declared()
    state = {row.storage: row for row in await service.resolve_state()}
    rendu: list[StorageOut] = []
    for table in declared.tables:
        row = state.get(table.storage)
        rendu.append(
            StorageOut(
                name=table.storage,
                label=table.label,
                model=table.model,
                schema_name=table.schema,
                table_name=table.table,
                keys=list(table.keys),
                projections=[
                    ProjectionOut(
                        column=p.column,
                        path="$." + ".".join(p.keys),
                        kind=p.kind,
                        sql_type=p.sql_type,
                    )
                    for p in table.projections
                ],
                indexes=[IndexOut(name=i.name, columns=list(i.columns)) for i in table.indexes],
                applied_at=row.applied_at if row is not None else None,
                version_number=row.version_number if row is not None else None,
                refusal=row.refusal if row is not None else None,
                refusal_detail=row.refusal_detail if row is not None else None,
            )
        )
    for refusal in declared.refusals:
        rendu.append(
            StorageOut(
                name=refusal.storage,
                label=refusal.storage,
                model="",
                schema_name="",
                table_name="",
                keys=[],
                projections=[],
                indexes=[],
                applied_at=None,
                version_number=None,
                refusal=refusal.code,
                refusal_detail=refusal.detail,
            )
        )
    return sorted(rendu, key=lambda item: item.name)


@router.get("/schema", response_model=dict[str, list[str]])
async def get_schema_preview(request: Request) -> object:
    """Le SQL que la version servie produirait, par storage. N'applique rien.

    La contrepartie de l'absence d'homologation : personne ne relit ce DDL avant qu'il
    s'applique, donc il est au moins lisible — avant comme après.
    """
    return await _service(request).resolve_preview()


@router.get("/{name}/objects", response_model=PageOut)
async def search_objects(
    name: str,
    request: Request,
    f: Annotated[list[str] | None, Query()] = None,
    tri: str | None = None,
    sens: str = "asc",
    page: int = 1,
    taille: int = PAGE_SIZE,
) -> object:
    """Les objets d'un storage qui satisfont les critères, page par page.

    Un critère s'écrit « colonne:operateur:valeur », et `f` se répète. La forme est
    délibérément plate : elle se lit dans une URL, donc dans un journal et dans un
    rapport d'incident, ce qu'un corps JSON ne permettrait pas sur une lecture.
    """
    service = _service(request)
    declared = await service.resolve_declared()
    table = next((t for t in declared.tables if t.storage == name), None)
    if table is None:
        refus = next((r for r in declared.refusals if r.storage == name), None)
        if refus is not None:
            # Déclaré mais refusé : ce n'est pas « inconnu », et le dire autrement
            # enverrait chercher une déclaration absente alors qu'elle est fautive.
            return _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": refus.code, "detail": refus.detail},
            )
        return _error(status.HTTP_404_NOT_FOUND, "storage_inconnu")
    try:
        criteria = [parse_criterion(raw) for raw in (f or [])]
        requete = build(
            table,
            criteria,
            sort=tri,
            descending=sens == "desc",
            page=page,
            page_size=taille,
        )
    except FilterError as refus:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": refus.code, "detail": refus.detail},
        )
    except IdentifierError as refus:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "nom_invalide", "detail": refus.name},
        )
    rows, total = await service.resolve_search(requete)
    colonnes = [p.column for p in table.projections]
    return PageOut(
        objects=[
            ObjectOut(
                cle=row["cle"],
                objet=_json(row["objet"]),
                vu_le=row["vu_le"],
                modifie_le=row["modifie_le"],
                origine=row["origine"],
                columns={nom: row[nom] for nom in colonnes},
            )
            for row in rows
        ],
        total=total,
        page=max(page, 1),
        page_size=min(max(taille, 1), 500),
    )


def _json(value: object) -> dict[str, Any]:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE, et une leçon du dépôt porte le jour
    # où un test l'a oublié.
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}
