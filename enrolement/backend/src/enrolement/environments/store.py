from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from enrolement.environments.model import Environment

# Les listes de colonnes sont écrites LITTÉRALEMENT dans chaque requête, jamais assemblées
# par interpolation : une f-string dans du SQL est une faute, et une constante partagée
# finit par voyager jusqu'à un endroit où elle n'en est plus une.


class EnvironmentDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


def _environment(row: Any) -> Environment:
    return Environment(
        row["id"],
        row["slug"],
        row["label"],
        row["created_at"],
        row["updated_at"],
        row["paired_base_url"],
        row["designated_base_url"],
    )


async def db_insert_environment(
    db: EnvironmentDb, environment_id: UUID, slug: str, label: str, now: datetime
) -> Environment:
    """Insère, et laisse la BASE trancher l'unicité du slug.

    Aucune lecture préalable : entre un `SELECT` et un `INSERT`, deux appels concurrents
    passent tous les deux. La violation remonte à l'appelant, qui la traduit en refus.
    """
    row = await db.fetchrow(
        "INSERT INTO environment (id, slug, label, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $4)"
        " RETURNING id, slug, label, created_at, updated_at,"
        " NULL::text AS paired_base_url, NULL::text AS designated_base_url",
        environment_id,
        slug,
        label,
        now,
    )
    return _environment(row)


async def db_update_environment(
    db: EnvironmentDb, environment_id: UUID, slug: str, label: str, now: datetime
) -> Environment | None:
    """Renomme. Rend nul si l'environnement n'existe plus — l'unicité reste à la base."""
    row = await db.fetchrow(
        "UPDATE environment e SET slug = $2, label = $3, updated_at = $4 WHERE e.id = $1"
        " RETURNING e.id, e.slug, e.label, e.created_at, e.updated_at,"
        " (SELECT p.base_url FROM environment_peer p WHERE p.environment_id = e.id)"
        " AS paired_base_url,"
        " (SELECT r.base_url FROM pairing_request r WHERE r.environment_id = e.id LIMIT 1)"
        " AS designated_base_url",
        environment_id,
        slug,
        label,
        now,
    )
    return None if row is None else _environment(row)


async def db_get_environment(db: EnvironmentDb, environment_id: UUID) -> Environment | None:
    row = await db.fetchrow(
        "SELECT e.id, e.slug, e.label, e.created_at, e.updated_at,"
        " (SELECT p.base_url FROM environment_peer p WHERE p.environment_id = e.id)"
        " AS paired_base_url,"
        " (SELECT r.base_url FROM pairing_request r WHERE r.environment_id = e.id LIMIT 1)"
        " AS designated_base_url"
        " FROM environment e WHERE e.id = $1",
        environment_id,
    )
    return None if row is None else _environment(row)


async def db_list_environments(db: EnvironmentDb, /) -> list[Environment]:
    # Trié par libellé : c'est ce que l'humain lit, et l'ordre de création ne veut rien
    # dire dans une liste qu'on parcourt pour reconnaître un nom.
    rows = await db.fetch(
        "SELECT e.id, e.slug, e.label, e.created_at, e.updated_at,"
        " (SELECT p.base_url FROM environment_peer p WHERE p.environment_id = e.id)"
        " AS paired_base_url,"
        " (SELECT r.base_url FROM pairing_request r WHERE r.environment_id = e.id LIMIT 1)"
        " AS designated_base_url"
        " FROM environment e ORDER BY e.label, e.slug"
    )
    return [_environment(row) for row in rows]


async def db_delete_environment(db: EnvironmentDb, environment_id: UUID) -> bool:
    """Supprime et dit si une ligne est partie.

    Le booléen rend la suppression atomique : deux suppressions concurrentes passent
    toutes deux la lecture préalable, et seule celle qui a effectivement retiré la ligne
    écrit son event.
    """
    return await db.execute("DELETE FROM environment WHERE id = $1", environment_id) != "DELETE 0"
