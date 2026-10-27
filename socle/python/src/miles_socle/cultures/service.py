from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import asyncpg
import structlog

from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

log = structlog.get_logger(__name__)

# Repli garanti de tout libellé déclinable : toujours active (cadrage, 15/10/2026).
FALLBACK_CULTURE = "en-US"
ACTIVATED_EVENT = "culture.activated"
DEACTIVATED_EVENT = "culture.deactivated"
EVENT_TYPES = frozenset({ACTIVATED_EVENT, DEACTIVATED_EVENT})
MAX_CODES_PER_CHANGE = 2000


class CulturesDb(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


@dataclass(frozen=True)
class Culture:
    code: str
    label_en: str
    label_native: str
    active: bool


class CultureError(Exception):
    """Changement refusé ; rien n'a été écrit."""


class FallbackCultureError(CultureError):
    def __init__(self) -> None:
        super().__init__(f"{FALLBACK_CULTURE} est le repli de l'installation")


class UnknownCulturesError(CultureError):
    def __init__(self, codes: Sequence[str]) -> None:
        super().__init__(f"{len(codes)} culture(s) inconnue(s)")
        self.codes = tuple(codes)


class EmptyChangeError(CultureError):
    def __init__(self) -> None:
        super().__init__("aucune culture désignée, ou trop")


def _culture(row: Any) -> Culture:
    return Culture(row["code"], row["label_en"], row["label_native"], row["active"])


async def db_list_cultures(db: CulturesDb, only_active: bool) -> list[Culture]:
    rows = await db.fetch(
        "SELECT code, label_en, label_native, active FROM cultures"
        " WHERE ($1::boolean IS FALSE OR active) ORDER BY code",
        only_active,
    )
    return [_culture(row) for row in rows]


@dataclass(frozen=True)
class CulturesService:
    """Référentiel donné des cultures : on n'y fait qu'activer et désactiver.

    Ni création, ni suppression, ni renommage : une liste saisie à la main dérive et
    finit par porter des codes inventés. Désactiver ne détruit rien de ce qui a été
    saisi pour la culture ; ces valeurs cessent seulement d'être servies.
    """

    pool: asyncpg.Pool
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_list(self, only_active: bool) -> list[Culture]:
        # Relu en base à chaque appel : une culture activée sert aussitôt, sans redémarrage.
        return await db_list_cultures(self.pool, only_active)

    async def resolve_set_active(
        self, author: EventAuthor, codes: Sequence[str], active: bool
    ) -> list[str]:
        """Applique exactement la sélection reçue ; rend les codes réellement changés."""
        wanted = sorted(set(codes))
        if not wanted or len(wanted) > MAX_CODES_PER_CHANGE:
            raise EmptyChangeError
        if not active and FALLBACK_CULTURE in wanted:
            raise FallbackCultureError
        async with self.pool.acquire() as conn, conn.transaction():
            found = {
                r["code"]
                for r in await conn.fetch(
                    "SELECT code FROM cultures WHERE code = ANY($1::text[]) ORDER BY code"
                    " FOR UPDATE",
                    wanted,
                )
            }
            unknown = [code for code in wanted if code not in found]
            if unknown:
                raise UnknownCulturesError(unknown)
            # Une culture déjà dans l'état voulu n'est pas « changée » : le rejeu ne
            # produit ni erreur ni event.
            rows = await conn.fetch(
                "UPDATE cultures SET active = $2 WHERE code = ANY($1::text[]) AND active <> $2"
                " RETURNING code",
                wanted,
                active,
            )
            changed = sorted(r["code"] for r in rows)
            if changed:
                event = NewEvent(
                    ACTIVATED_EVENT if active else DEACTIVATED_EVENT,
                    tuple(ObjectRef("culture", code) for code in changed),
                    author,
                    {"count": len(changed)},
                )
                await db_write_event(conn, event, self.catalog, self.now)
        log.info("cultures_changees", active=active, count=len(changed))
        return changed
