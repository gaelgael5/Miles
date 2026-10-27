from __future__ import annotations

from typing import Protocol

import asyncpg
from pydantic import SecretStr


class DatabaseAccess(Protocol):
    """Ce dont le socle a besoin pour joindre une base, sans savoir d'où ça vient.

    Divergence volontaire : le pool importait `miles.config.DatabaseSettings`, ce qui
    faisait dépendre le socle du produit qui le consomme. Chaque produit garde sa propre
    classe de configuration — elle porte son préfixe d'environnement et ses défauts — et
    le socle n'en connaît que la forme.
    """

    @property
    def database_url(self) -> SecretStr: ...

    @property
    def db_pool_min_size(self) -> int: ...

    @property
    def db_pool_max_size(self) -> int: ...

    @property
    def db_connect_timeout_s(self) -> float: ...


async def db_create_pool(settings: DatabaseAccess) -> asyncpg.Pool:
    # Point d'injection unique de l'URL de base : le secret n'est déballé qu'ici.
    return await asyncpg.create_pool(
        dsn=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_connect_timeout_s,
    )


async def db_connect(settings: DatabaseAccess) -> asyncpg.Connection:
    # Connexion isolée, hors pool, pour les migrations : le verrou consultatif
    # est tenu par la session et doit rester sur la même connexion.
    return await asyncpg.connect(
        dsn=settings.database_url.get_secret_value(),
        timeout=settings.db_connect_timeout_s,
    )
