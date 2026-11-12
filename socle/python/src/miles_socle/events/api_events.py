"""`GET /api/events` : le journal, filtré et borné.

Session exigée — le portillon s'en charge, cette route n'étant dans aucune liste de
passage. Le journal dit qui a fait quoi : l'ouvrir rendrait publique l'activité des
administrateurs d'une instance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from miles_socle.events.search import PAGE_SIZE, EventFilter, SearchRefusal
from miles_socle.events.service import EventsService, SearchResult

router = APIRouter()

EVENTS_PATH = "/api/events"


class ObjectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    sequence: int


class EventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    functional_at: datetime
    # 'write_time' : l'appelant n'avait pas de date métier. Rendu au lecteur, qui ne doit
    # pas prendre une date d'écriture pour une date fonctionnelle.
    functional_at_source: str
    written_at: datetime
    author_directory: str
    author_subject: str
    properties: dict[str, Any]
    objects: list[ObjectOut]
    # Les champs de la racine commune (12/11/2026). Rendus même nuls : l'écran doit pouvoir
    # dire « pas d'identifiant externe » plutôt que de laisser croire qu'il ne sait pas.
    external_id: str | None = None
    dedup_key: str | None = None
    creation_date: datetime | None = None


class WindowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    # Vrai quand l'appelant n'a donné aucune borne : l'écran DOIT le dire, sinon il montre
    # une semaine en laissant croire qu'il montre tout le journal.
    defaulted: bool


class EventsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventOut]
    total: int
    page: int
    size: int
    window: WindowOut
    missing_sequences: list[int]


def _service(request: Request) -> EventsService:
    service: EventsService = request.app.state.events
    return service


@router.get(EVENTS_PATH, response_model=EventsOut)
async def get_events(
    request: Request,
    type: str | None = None,
    author_directory: str | None = None,
    author_subject: str | None = None,
    object_kind: str | None = None,
    object_id: str | None = None,
    written_from: datetime | None = None,
    written_to: datetime | None = None,
    functional_from: datetime | None = None,
    functional_to: datetime | None = None,
    page: int = Query(default=1),
    size: int = Query(default=PAGE_SIZE),
) -> EventsOut:
    filtre = EventFilter(
        type=type,
        author_directory=author_directory,
        author_subject=author_subject,
        object_kind=object_kind,
        object_id=object_id,
        written_from=written_from,
        written_to=written_to,
        functional_from=functional_from,
        functional_to=functional_to,
    )
    try:
        return _out(await _service(request).resolve_search(filtre, page, size))
    except SearchRefusal as refus:
        # 400 et non 422 : le filtre est syntaxiquement recevable, c'est sa COMBINAISON qui
        # ne veut rien dire. Le code et le détail sont rendus, pour que l'écran puisse dire
        # laquelle plutôt qu'« erreur ».
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": refus.code, "detail": refus.detail},
        ) from refus


def _out(resultat: SearchResult) -> EventsOut:
    return EventsOut(
        events=[
            EventOut(
                id=event.id,
                type=event.type,
                functional_at=event.functional_at,
                functional_at_source=event.functional_at_source,
                written_at=event.written_at,
                author_directory=event.author_directory,
                author_subject=event.author_subject,
                properties=event.properties,
                objects=[
                    ObjectOut(kind=o.kind, id=o.id, sequence=o.sequence) for o in event.objects
                ],
                external_id=event.external_id,
                dedup_key=event.dedup_key,
                creation_date=event.creation_date,
            )
            for event in resultat.page.events
        ],
        total=resultat.page.total,
        page=resultat.page.page,
        size=resultat.page.size,
        window=WindowOut(
            start=resultat.window.start,
            end=resultat.window.end,
            defaulted=resultat.window.defaulted,
        ),
        missing_sequences=list(resultat.missing_sequences),
    )
