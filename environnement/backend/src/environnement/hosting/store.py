"""Les requêtes de la version hébergée. Une seule ligne, et la base le garantit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from environnement.hosting.model import HostedVersion

# Les listes de colonnes sont écrites LITTÉRALEMENT dans chaque requête : les factoriser
# rendrait illisible ce que chacune touche, et c'est ce qu'on vient vérifier quand une
# ligne est fausse.


class HostingDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


def _hosted(row: Any) -> HostedVersion:
    return HostedVersion(
        row["workspace_id"],
        int(row["ordered_number"]),
        row["ordered_commit"],
        row["ordered_at"],
        row["served_commit"],
        row["served_at"],
        row["refusal"],
    )


async def db_get_hosted_version(db: HostingDb, /) -> HostedVersion | None:
    row = await db.fetchrow(
        "SELECT workspace_id, ordered_number, ordered_commit, ordered_at, served_commit,"
        " served_at, refusal FROM hosted_version WHERE id = 'self'"
    )
    return None if row is None else _hosted(row)


async def db_record_order(
    db: HostingDb, workspace_id: str, number: int, commit: str, now: datetime
) -> None:
    """Enregistre l'ordre reçu, et EFFACE la trace de l'application précédente.

    L'effacement n'est pas un détail : garder l'ancien `served_commit` ferait répondre à
    l'enrôlement qu'on sert déjà, alors que l'ordre vient de changer — et la comparaison
    qu'il fait porte sur le commit qu'il a ordonné.

    Un ordre IDENTIQUE rejoué passe aussi par ici, et c'est voulu : ce qui décide s'il y a
    quelque chose à faire est l'ARBRE posé, pas cette ligne.
    """
    await db.execute(
        "INSERT INTO hosted_version (id, workspace_id, ordered_number, ordered_commit,"
        " ordered_at, served_commit, served_at, refusal)"
        " VALUES ('self', $1, $2, $3, $4, NULL, NULL, NULL)"
        " ON CONFLICT (id) DO UPDATE SET workspace_id = excluded.workspace_id,"
        " ordered_number = excluded.ordered_number, ordered_commit = excluded.ordered_commit,"
        " ordered_at = excluded.ordered_at, served_commit = NULL, served_at = NULL,"
        " refusal = NULL",
        workspace_id,
        number,
        commit,
        now,
    )


async def db_record_served(db: HostingDb, commit: str, now: datetime) -> None:
    await db.execute(
        "UPDATE hosted_version SET served_commit = $1, served_at = $2, refusal = NULL"
        " WHERE id = 'self'",
        commit,
        now,
    )


async def db_record_refusal(db: HostingDb, refusal: str) -> None:
    """Écrit le refus. La base interdit qu'il coexiste avec un commit servi."""
    await db.execute(
        "UPDATE hosted_version SET served_commit = NULL, served_at = NULL, refusal = $1"
        " WHERE id = 'self'",
        refusal,
    )
