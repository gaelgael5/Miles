from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg
import structlog

from miles.db.migrations import db_schema_version

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HealthReport:
    database_reachable: bool
    schema_version: int | None
    expected_schema_version: int

    @property
    def healthy(self) -> bool:
        # Un schéma en retard rend le service malade : servir avec un schéma
        # incomplet est la panne silencieuse qu'un contrôle de santé doit révéler.
        return self.database_reachable and self.schema_version == self.expected_schema_version


HealthProbe = Callable[[], Awaitable[HealthReport]]


async def resolve_health(
    pool: asyncpg.Pool, expected_schema_version: int, timeout_s: float
) -> HealthReport:
    """Interroge réellement la base : jamais de santé déduite d'un état en cache."""
    try:
        async with asyncio.timeout(timeout_s), pool.acquire() as conn:
            version = await db_schema_version(conn)
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        log.warning("base_injoignable", error_type=type(exc).__name__)
        return HealthReport(False, None, expected_schema_version)
    return HealthReport(True, version, expected_schema_version)
