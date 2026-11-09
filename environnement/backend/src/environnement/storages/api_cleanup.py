"""Montrer ce que les règles de nettoyage SUPPRIMERAIENT, sans rien supprimer. `45543845`.

« On doit pouvoir répondre à "montre-moi ce que tu supprimerais" sans rien supprimer » :
c'est une décision du ticket, et c'est une route de LECTURE. Elle n'offre pas de
déclencher le nettoyage — le déclenchement est la fin d'un import `traite`, et rien
d'autre (voir `ingestion/cleanup.py`). Ajouter ici un bouton qui supprime demanderait un
arbitrage de Gael, qui a écarté le 09/11/2026 le sujet d'un storage qui ne reçoit plus
d'import.

À part de `api_storages.py`, qui montre ce qu'un storage CONTIENT : ici on montre ce qu'il
PERDRAIT, ce qui n'est pas une recherche mais la lecture d'une règle.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from environnement.ingestion.cleanup_rules import (
    CleanupRule,
    count_statement,
    page_statement,
    removable,
    rule_id,
    rules_of,
    threshold,
)
from environnement.sources.declarations import file_declared_sources
from environnement.storages.model import (
    REFUSAL_TABLE_ABSENT,
    REFUSAL_TABLE_BEHIND,
    StorageTable,
)
from environnement.storages.query import MAX_PAGE_SIZE, PAGE_SIZE
from environnement.storages.service import StoragesService

router = APIRouter(prefix="/api/storages")


class RuleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Le nom par lequel la règle se demande : dérivé de ce qu'elle est, jamais de son rang.
    id: str
    kind: str
    days: int
    # Le chemin DÉCLARÉ de la propriété (péremption), ou la source dont l'entrée porte la
    # règle (absents). Jamais le nom de colonne interne : l'écran montre ce que la
    # personne a choisi.
    property: str | None
    source: str | None
    # Combien d'items cette règle désigne en ce moment. Compté, pas estimé.
    designated: int


class DesignatedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cle: str
    objet: dict[str, Any]
    vu_le: datetime
    absent_depuis: datetime | None
    # La valeur que la règle a lue — la date de la marque, ou la propriété datée. Rendue
    # BRUTE : c'est elle qu'on va corriger quand elle n'est pas une date.
    value: str | None
    # L'item sortirait-il vraiment ? Faux quand la valeur a la FORME d'une date sans en
    # être une (« 2026-02-30 ») : la suppression l'épargne, et le montrer ici est la seule
    # façon que quelqu'un l'apprenne et aille corriger la donnée.
    removable: bool


class CleanupOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[RuleOut]
    # Les règles de péremption qu'on ne sait plus évaluer, par le chemin qu'elles nomment.
    # Non vide : le nettoyage de ce storage est refusé EN ENTIER, et l'écran doit le dire —
    # les comptes ci-dessus restent ce que les règles désigneraient, pas ce qui sortira.
    refused: list[str]
    # La règle dont la page est rendue, nulle quand aucune règle n'est déclarée.
    rule: str | None
    objects: list[DesignatedOut]
    total: int
    page: int
    page_size: int


def _service(request: Request) -> StoragesService:
    service: StoragesService = request.app.state.storages
    return service


def _error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("/{name}/nettoyage", response_model=CleanupOut)
async def preview_cleanup(
    name: str,
    request: Request,
    regle: str | None = None,
    page: int = 1,
    taille: int = PAGE_SIZE,
) -> object:
    """Ce que les règles de nettoyage de ce storage supprimeraient, page par page.

    Toutes les règles avec leur compte, et la page d'UNE d'entre elles — la première par
    défaut, celle que `regle` nomme sinon. Une page par règle et non une page mêlée : un
    item sort pour UNE raison, et un écran qui les additionnerait ne dirait pas laquelle.
    """
    service = _service(request)
    declared = await service.resolve_declared()
    table = next((t for t in declared.tables if t.storage == name), None)
    if table is None:
        refus = next((r for r in declared.refusals if r.storage == name), None)
        if refus is not None:
            return _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": refus.code, "detail": refus.detail},
            )
        return _error(status.HTTP_404_NOT_FOUND, "storage_inconnu")
    manquantes = await service.resolve_lag(table)
    if manquantes is None:
        return _error(
            status.HTTP_409_CONFLICT,
            {"code": REFUSAL_TABLE_ABSENT, "detail": f"{table.schema}.{table.table}"},
        )
    if manquantes:
        # La table est en retard d'une colonne que la version servie déclare : la règle
        # porterait sur une colonne qui n'existe pas encore, et PostgreSQL rendrait un 500
        # qui n'apprend rien. Même refus qu'à la recherche d'objets, avec le geste qui le
        # referme — poser la version.
        return _error(
            status.HTTP_409_CONFLICT,
            {"code": REFUSAL_TABLE_BEHIND, "detail": ", ".join(manquantes)},
        )
    paths = await service.tree.file_paths()
    sources = await file_declared_sources(service.tree.file_text, paths)
    regles = rules_of(table, list(sources.readable.values()))
    maintenant = service.now()
    comptes = [await _designated_count(service, table, rule, maintenant) for rule in regles]
    if regle is None:
        # La première par défaut : l'écran ouvre sur quelque chose plutôt que sur un choix
        # à faire avant d'avoir rien vu.
        choisie = regles[0] if regles else None
    else:
        choisie = next((r for r in regles if rule_id(r) == regle), None)
        if choisie is None:
            # Nommée et refusée : une règle demandée qui n'existe pas est le plus souvent
            # une règle qui vient d'être retirée de la version servie, et répondre la
            # première ferait lire des comptes sous le nom d'une autre.
            return _error(status.HTTP_404_NOT_FOUND, "regle_inconnue")
    rendu = CleanupOut(
        rules=[
            RuleOut(
                id=rule_id(rule),
                kind=rule.kind,
                days=rule.days,
                property=rule.path,
                source=rule.source,
                designated=compte,
            )
            for rule, compte in zip(regles, comptes, strict=True)
        ],
        refused=list(table.unresolved_expiries),
        rule=None if choisie is None else rule_id(choisie),
        objects=[],
        total=0,
        page=max(page, 1),
        page_size=min(max(taille, 1), MAX_PAGE_SIZE),
    )
    if choisie is None:
        # Aucune règle déclarée : rien à montrer, et ce n'est pas une erreur — c'est le
        # défaut d'un storage qui ne se nettoie pas.
        return rendu
    lignes, total = await service.resolve_designated(
        page_statement(table, choisie),
        count_statement(table, choisie),
        threshold=threshold(choisie, maintenant),
        limit=rendu.page_size,
        offset=(rendu.page - 1) * rendu.page_size,
    )
    rendu.objects = [_designated(choisie, row) for row in lignes]
    rendu.total = total
    return rendu


async def _designated_count(
    service: StoragesService, table: StorageTable, rule: CleanupRule, now: datetime
) -> int:
    """Le compte d'une règle. Une instruction par règle : un storage en porte une poignée."""
    _, total = await service.resolve_designated(
        page_statement(table, rule),
        count_statement(table, rule),
        threshold=threshold(rule, now),
        # Zéro ligne : on ne veut que le compte, et une page vide coûte une recherche
        # d'index bornée. Le même couple d'instructions qu'au-dessus, pour que le compte
        # annoncé soit celui de la clause que la page emprunte.
        limit=0,
        offset=0,
    )
    return total


def _designated(rule: CleanupRule, row: Any) -> DesignatedOut:
    valeur = row["valeur"]
    return DesignatedOut(
        cle=row["cle"],
        objet=_json(row["objet"]),
        vu_le=row["vu_le"],
        absent_depuis=row["absent_depuis"],
        value=None if valeur is None else str(valeur),
        removable=removable(rule, valeur),
    )


def _json(value: object) -> dict[str, Any]:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE : leçon du dépôt.
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}
