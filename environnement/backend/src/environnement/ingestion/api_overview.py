"""Les routes de l'écran du service d'ingestion : son état, et le journal des appels.

Sous `/api`, donc derrière le portillon de sessions, et réservées à l'administrateur
comme toute route qu'il ne liste pas. **Une clé d'ingestion n'ouvre jamais ces routes** :
elle ne sait que déposer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from environnement.ingestion.api_ingest_file import INGEST_OPERATIONS
from environnement.ingestion.overview import PAGE_SIZE, CallPage, Health, IngestionOverview
from environnement.ingestion.store import Call

router = APIRouter(prefix="/api/ingestion")


def overview_service(request: Request) -> IngestionOverview:
    service: IngestionOverview = request.app.state.ingestion_overview
    return service


Service = Annotated[IngestionOverview, Depends(overview_service)]


class EndpointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    storage: str
    entry_model: str
    mode: str
    # L'adresse complète à appeler : c'est la seule façon de répondre à « où est-ce que
    # je pousse ? » sans faire lire un fichier de paramétrage.
    path: str
    served: bool


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Nuls quand aucune version n'est servie : sans version, aucune source n'est
    # déclarée, donc aucun point d'entrée n'existe. L'écran doit pouvoir le dire.
    version_number: int | None
    version_commit: str | None
    version_served_at: datetime | None
    endpoints: list[EndpointOut]
    unreadable_sources: list[str]
    active_keys: int
    never_used_keys: int
    deposits_total: int
    deposits_recent: int
    last_deposit_at: datetime | None
    # Les modes de masse que le paramétrage peut déclarer et que la stack ne sert pas
    # encore. L'écran dit qu'il n'y a rien à surveiller, et pourquoi.
    bulk_modes: list[str]


class CallOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: str
    mode: str
    entry_model: str
    object_count: int
    size_bytes: int
    version_number: int
    key_label: str
    # Le préfixe affiché, et JAMAIS la valeur. Nul si la clé n'est plus en base.
    key_prefix: str | None
    received_at: datetime
    state: str


class CallsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calls: list[CallOut]
    total: int
    page: int
    page_size: int
    # Les sources que la version servie déclare : le filtre ne propose que celles-là,
    # plutôt que de laisser découvrir qu'un nom ne rend rien.
    sources: list[str]


def _endpoint(point: object) -> EndpointOut:
    return EndpointOut.model_validate(point, from_attributes=True)


def _health(etat: Health) -> HealthOut:
    return HealthOut(
        version_number=etat.version_number,
        version_commit=etat.version_commit,
        version_served_at=etat.version_served_at,
        endpoints=[_endpoint(point) for point in etat.endpoints],
        unreadable_sources=list(etat.unreadable_sources),
        active_keys=etat.active_keys,
        never_used_keys=etat.never_used_keys,
        deposits_total=etat.deposits_total,
        deposits_recent=etat.deposits_recent,
        last_deposit_at=etat.last_deposit_at,
        bulk_modes=list(etat.bulk_modes),
    )


def _call(appel: Call) -> CallOut:
    return CallOut.model_validate(appel, from_attributes=True)


def _calls(page: CallPage, sources: tuple[str, ...]) -> CallsOut:
    return CallsOut(
        calls=[_call(appel) for appel in page.calls],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        sources=list(sources),
    )


@router.get("/health", response_model=HealthOut)
async def health(service: Service) -> object:
    return _health(await service.resolve_health(operations=INGEST_OPERATIONS))


@router.get("/calls", response_model=CallsOut)
async def calls(
    service: Service,
    source: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    taille: Annotated[int, Query(ge=1)] = PAGE_SIZE,
) -> object:
    page_lue = await service.resolve_calls(source=source, page=page, page_size=taille)
    return _calls(page_lue, await service.resolve_declared_sources())
