"""Les routes de l'écran du service d'ingestion : son état, et le journal des appels.

Sous `/api`, donc derrière le portillon de sessions, et réservées à l'administrateur
comme toute route qu'il ne liste pas. **Une clé d'ingestion n'ouvre jamais ces routes** :
elle ne sait que déposer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from environnement.ingestion.api_ingest_file import INGEST_OPERATIONS
from environnement.ingestion.overview import PAGE_SIZE, CallPage, Health, IngestionOverview
from environnement.ingestion.store import Call, CallOutcome

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


class RejectionReasonOut(BaseModel):
    """Un motif de rejet et son compte, pour corriger un modèle sans deviner."""

    model_config = ConfigDict(extra="forbid")
    reason: str
    detail: str | None
    count: int
    # Un objet rejeté sous ce motif, pour aller lire un cas réel. Nul quand la clé n'a pas
    # pu être extraite — ce qui est justement l'un des motifs possibles.
    sample_key: str | None


class CallOutcomeOut(BaseModel):
    """Ce qu'un dépôt est devenu. Distinct du compte-rendu PUBLIÉ aux modes synchrones :
    celui-ci est l'écran d'un administrateur, et il porte la synthèse des motifs, que le
    contrat ne promet pas."""

    model_config = ConfigDict(extra="forbid")
    id: str
    state: str
    # Les quatre instants : l'attente en file, la lecture, l'écriture. Rendus BRUTS, et
    # non en durées calculées ici — c'est l'écran qui sait dans quelle culture il les
    # présente, et une durée calculée côté serveur perdrait les bornes qui l'expliquent.
    received_at: datetime
    started_at: datetime | None
    apply_started_at: datetime | None
    finished_at: datetime | None
    items_read: int | None
    failure_code: str | None
    failure_detail: str | None
    received: int | None
    written: int | None
    unchanged: int | None
    rejected: int | None
    reasons: list[RejectionReasonOut]
    anomalies: list[str]


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


def _outcome(issue: CallOutcome) -> CallOutcomeOut:
    rapport = issue.report
    return CallOutcomeOut(
        id=issue.id,
        state=issue.state,
        received_at=issue.received_at,
        started_at=issue.started_at,
        apply_started_at=issue.apply_started_at,
        finished_at=issue.finished_at,
        items_read=issue.items_read,
        failure_code=issue.failure_code,
        failure_detail=issue.failure_detail,
        received=None if rapport is None else rapport.received,
        written=None if rapport is None else rapport.written,
        unchanged=None if rapport is None else rapport.unchanged,
        rejected=None if rapport is None else rapport.rejected,
        reasons=(
            []
            if rapport is None
            else [RejectionReasonOut(**motif.as_json()) for motif in rapport.reasons]
        ),
        anomalies=[] if rapport is None else list(rapport.anomalies),
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


@router.get(
    "/calls/{ingestion_id}",
    response_model=CallOutcomeOut,
    responses={404: {"description": "Aucun dépôt ne porte cet identifiant."}},
)
async def call_outcome(ingestion_id: str, service: Service) -> object:
    """Le détail d'UN dépôt, lu quand on ouvre sa ligne du journal.

    À part de la liste, et c'est délibéré : un compte-rendu d'import porte jusqu'à deux
    cents objets et sa synthèse de motifs, qu'on ne regarde qu'une fois.
    """
    issue = await service.resolve_call_outcome(ingestion_id)
    if issue is None:
        raise HTTPException(status_code=404, detail={"code": "depot_inconnu", "detail": None})
    return _outcome(issue)
