from __future__ import annotations

import asyncpg

from miles.config import Settings


async def db_create_pool(settings: Settings) -> asyncpg.Pool:
    # Point d'injection unique de l'URL de base : le secret n'est déballé qu'ici.
    return await asyncpg.create_pool(
        dsn=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_connect_timeout_s,
    )


async def db_connect(settings: Settings) -> asyncpg.Connection:
    # Connexion isolée, hors pool, pour les migrations : le verrou consultatif
    # est tenu par la session et doit rester sur la même connexion.
    return await asyncpg.connect(
        dsn=settings.database_url.get_secret_value(),
        timeout=settings.db_connect_timeout_s,
    )
