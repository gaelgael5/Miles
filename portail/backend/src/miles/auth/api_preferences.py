from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from miles.auth.author import request_author
from miles.cultures.service import CulturesService
from miles.events.model import EventAuthor

# Ouvertes à toute session, OIDC sans droit comprise (liste OIDC_SESSION_PATHS de la
# passerelle) : une préférence personnelle n'atteint rien d'autre que la personne.
router = APIRouter(prefix="/api/auth/me/preferences")


class UnknownLanguageError(Exception):
    pass


@dataclass(frozen=True)
class PreferencesService:
    """Préférences personnelles d'une identité (ticket 0a52596d) : la langue du portail."""

    pool: asyncpg.Pool
    cultures: CulturesService
    now: Callable[[], datetime]

    async def resolve_language(self, viewer: EventAuthor) -> str | None:
        value = await self.pool.fetchval(
            "SELECT language FROM user_preferences"
            " WHERE viewer_directory = $1 AND viewer_subject = $2",
            viewer.directory,
            viewer.subject,
        )
        return str(value) if value is not None else None

    async def resolve_set_language(self, viewer: EventAuthor, language: str) -> None:
        active = {c.code for c in await self.cultures.resolve_list(only_active=True)}
        # Seule une culture active se retient : une valeur inconnue serait gardée en base
        # et ressortirait à chaque connexion. La traduction du portail, elle, se juge à
        # l'écran, qui retombe sur en-US pour une culture qu'il ne sait pas afficher.
        if language not in active:
            raise UnknownLanguageError(language)
        await self.pool.execute(
            "INSERT INTO user_preferences (viewer_directory, viewer_subject, language,"
            " updated_at) VALUES ($1, $2, $3, $4) ON CONFLICT (viewer_directory, viewer_subject)"
            " DO UPDATE SET language = EXCLUDED.language, updated_at = EXCLUDED.updated_at",
            viewer.directory,
            viewer.subject,
            language,
            self.now(),
        )


def preferences_service(request: Request) -> PreferencesService:
    service: PreferencesService = request.app.state.preferences
    return service


Service = Annotated[PreferencesService, Depends(preferences_service)]


class PreferencesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None : aucun choix retenu ; le portail suit l'écran de connexion, puis en-US.
    language: str | None


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(max_length=32)


@router.get("", response_model=PreferencesOut)
async def get_preferences(request: Request, service: Service) -> PreferencesOut:
    return PreferencesOut(language=await service.resolve_language(request_author(request)))


@router.put("", response_model=PreferencesOut)
async def set_preferences(body: PreferencesIn, request: Request, service: Service) -> object:
    try:
        await service.resolve_set_language(request_author(request), body.language)
    except UnknownLanguageError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": {"field": "language"}},
        )
    return PreferencesOut(language=body.language)
