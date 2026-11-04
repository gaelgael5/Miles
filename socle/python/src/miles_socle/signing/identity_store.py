"""Accès à `module_identity` : la paire de clés que le module détient.

Le SQL est ici, la TABLE est chez chaque produit. Ce n'est pas une incohérence : le socle
ne porte aucune migration (décision du 27/10/2026), parce que le schéma d'un produit est
relu par un humain produit par produit. Il porte en revanche les requêtes de ses propres
tables, comme il le fait déjà pour les secrets, les sessions et le journal — sans quoi
chaque produit réécrirait les mêmes cinq requêtes et elles divergeraient.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from miles_socle.signing.identity_model import SINGLETON, ModuleIdentity
from miles_socle.signing.keys import ALGORITHM


class IdentityDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


async def db_get_identity(db: IdentityDb, /) -> ModuleIdentity | None:
    row = await db.fetchrow(
        "SELECT public_key, algorithm, created_at FROM module_identity WHERE id = $1", SINGLETON
    )
    if row is None:
        return None
    return ModuleIdentity(row["public_key"], row["algorithm"], row["created_at"])


async def db_get_private_key_slug(db: IdentityDb, /) -> str | None:
    row = await db.fetchrow(
        "SELECT private_key_secret_slug FROM module_identity WHERE id = $1", SINGLETON
    )
    return None if row is None else str(row["private_key_secret_slug"])


async def db_lock_identity(db: IdentityDb, key: int) -> None:
    """Sérialise la pose de l'identité, pour la durée de la TRANSACTION.

    Sans ce verrou, poser l'identité serait un « lire puis écrire » : deux instances qui
    démarrent en même temps liraient toutes deux « aucune identité », engendreraient deux
    paires, et la seconde écraserait celle de la première — donc l'appariement. Le verrou
    rend atomique la lecture et l'écriture qui suivent, et PostgreSQL le relâche au commit
    comme au rollback, sans rien à nettoyer.
    """
    await db.execute("SELECT pg_advisory_xact_lock($1)", key)


async def db_secret_exists(db: IdentityDb, slug: str) -> bool:
    """Un secret porte-t-il déjà ce slug ? Lu pour ÉVITER une violation d'unicité.

    L'écran générique des secrets admet n'importe quel slug : si quelqu'un a créé le
    nôtre à la main, l'insertion échouerait et avorterait la transaction entière — ce
    qu'aucun try/except ne rattrape. On préfère un refus qui nomme la cause.
    """
    return await db.fetchrow("SELECT 1 FROM secrets WHERE slug = $1", slug) is not None


async def db_insert_identity(
    db: IdentityDb, public_key: str, secret_slug: str, now: datetime
) -> ModuleIdentity:
    """Écrit l'identité. À n'appeler que sous `db_lock_identity`, et après le secret visé."""
    row = await db.fetchrow(
        "INSERT INTO module_identity (id, public_key, private_key_secret_slug, algorithm,"
        " created_at) VALUES ($1, $2, $3, $4, $5)"
        " RETURNING public_key, algorithm, created_at",
        SINGLETON,
        public_key,
        secret_slug,
        ALGORITHM,
        now,
    )
    return ModuleIdentity(row["public_key"], row["algorithm"], row["created_at"])
