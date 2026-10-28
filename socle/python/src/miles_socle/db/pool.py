from __future__ import annotations

from typing import Protocol

import asyncpg
from pydantic import SecretStr


class DatabaseAccess(Protocol):
    """Ce dont le socle a besoin pour joindre une base, sans savoir d'où ça vient.

    Un Protocol, bien que `SocleDatabaseSettings` existe désormais au socle et le satisfasse :
    le pool n'a pas à exiger pydantic. Un harnais de test, un script ou un outil peut lui
    passer un objet de la bonne FORME, et c'est ce qui permet au montage des tests
    d'intégration de câbler sans construire une configuration complète.

    Historique utile : le pool importait `miles.config.DatabaseSettings`, ce qui faisait
    dépendre le socle du produit qui le consomme. L'inversion a été faite le 27/10/2026 ;
    ne pas la défaire au motif que la classe de base est maintenant ici.
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
