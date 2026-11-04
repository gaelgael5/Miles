"""Les requêtes de l'aire de préparation d'un import. Rien ne décide ici.

L'aire existe pour tenir l'interdit du ticket `0f14adbd` : **ne pas garder la transaction
d'écriture ouverte pendant le parsing et la transformation.** Les items transformés y
attendent, hors transaction, et une seule transaction courte les confronte ensuite à la
table du storage.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from environnement.ingestion.preparation import PreparedObject

STAGED_TO_WRITE = "a_ecrire"
STAGED_REJECTED = "rejete"


class StagingDb(Protocol):
    """Ce que ce module demande à une connexion : de quoi doubler sans monter une base."""

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def executemany(self, query: str, args: Any) -> Any: ...


async def db_stage(db: StagingDb, ingestion_id: str, items: list[PreparedObject]) -> None:
    """Range un lot d'items préparés. Un lot vide n'écrit rien.

    `executemany` et non une instruction par item : la préparation écrit tous les
    `lot_ecriture` items, et un aller-retour par item ferait de l'écriture le coût
    dominant d'un import de cinquante mille lignes.
    """
    if not items:
        return
    await db.executemany(
        "INSERT INTO ingestion_staging"
        " (ingestion_id, position, outcome, cle, objet, empreinte, reason, detail)"
        " VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)",
        [
            (
                ingestion_id,
                item.position,
                STAGED_TO_WRITE if item.writable else STAGED_REJECTED,
                item.key,
                None if item.objet is None else json.dumps(item.objet, ensure_ascii=False),
                item.empreinte,
                item.reason,
                item.detail,
            )
            for item in items
        ],
    )


async def db_staged(
    db: StagingDb, ingestion_id: str, *, after: int, limit: int
) -> list[PreparedObject]:
    """Les items préparés, par rang croissant, au-delà de `after`.

    Par rang croissant, et c'est une règle et non un détail : « deux items de même clé,
    le dernier valide gagne » suppose un ordre d'écriture, et c'est celui du document.
    """
    rows = await db.fetch(
        "SELECT position, outcome, cle, objet, empreinte, reason, detail"
        " FROM ingestion_staging"
        " WHERE ingestion_id = $1 AND position > $2 ORDER BY position LIMIT $3",
        ingestion_id,
        after,
        limit,
    )
    return [_item(row) for row in rows]


async def db_clear_staging(db: StagingDb, ingestion_id: str) -> None:
    """Abandonne l'aire de préparation de cet import.

    Appelée aussi bien après une écriture réussie qu'après un abandon (critère 7) :
    l'aire est un brouillon, et ce qui reste de l'import est son compte-rendu.
    """
    await db.execute("DELETE FROM ingestion_staging WHERE ingestion_id = $1", ingestion_id)


def _item(row: Any) -> PreparedObject:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE, pas en dictionnaire : le journal du
    # socle le sait déjà, et un test l'avait appris à ses dépens le 28/10/2026.
    brut = row["objet"]
    objet = None if brut is None else (json.loads(brut) if isinstance(brut, str) else brut)
    empreinte = row["empreinte"]
    return PreparedObject(
        position=int(row["position"]),
        key=row["cle"],
        objet=objet,
        empreinte=None if empreinte is None else bytes(empreinte),
        reason=row["reason"],
        detail=row["detail"],
    )


async def db_duplicate_keys(db: StagingDb, ingestion_id: str, *, limit: int) -> list[str]:
    """Les clés portées deux fois ou plus par les items à écrire de cet import.

    En SQL et non en mémoire : tenir l'ensemble des clés d'un document de cinquante mille
    items pendant sa lecture aurait rendu en mémoire ce que la lecture en flux évite. La
    sortie est bornée — on signale une source qui se contredit, on n'en dresse pas
    l'inventaire.
    """
    rows = await db.fetch(
        "SELECT cle FROM ingestion_staging"
        " WHERE ingestion_id = $1 AND outcome = $2 AND cle IS NOT NULL"
        " GROUP BY cle HAVING count(*) > 1 ORDER BY min(position) LIMIT $3",
        ingestion_id,
        STAGED_TO_WRITE,
        limit,
    )
    return [row["cle"] for row in rows]
