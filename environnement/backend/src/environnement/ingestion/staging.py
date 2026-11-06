"""La TABLE TEMPORAIRE d'un import : l'ouvrir vide, y copier en masse, la relire, la fermer.

**Une table temporaire, et non plus une table permanente partagée** (Gael, 06/11/2026 :
« on doit avoir une table temporaire vide permettant l'import »). L'ancienne
`ingestion_staging` était une vraie table du schéma, donc journalisée au WAL, vidée par un
`DELETE` à chaque passage — des tuples morts à chaque import, sur une table qu'aucun autre
usage ne lit. Une table TEMP n'est écrite dans aucun WAL, n'est visible que de la session
qui l'a créée, et se ferme par un `DROP` instantané au lieu d'un `DELETE` à nettoyer.

Elle est posée VIDE à chaque import — `DROP` avant `CREATE` — parce que la connexion vient
d'un pool : celle qui a mené l'import précédent peut revenir, et un reliquat ferait écrire
les items d'un autre document.

L'aire existe pour tenir l'interdit du ticket `0f14adbd` : **ne pas garder la transaction
d'écriture ouverte pendant le parsing et la transformation.** Les items transformés y
attendent, hors transaction, et une seule transaction courte les confronte ensuite à la
table du storage. Rien ne décide ici.

**Perdre cette table n'est pas perdre l'import** : une interruption laisse l'ingestion « en
cours », l'entretien la remet en file, et tout est refait depuis le document posé sur le
disque. C'est ce qui autorise à ne pas la journaliser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from environnement.ingestion.preparation import PreparedObject

PREPARED_TABLE = "ingestion_prepared"
STAGED_TO_WRITE = "a_ecrire"
STAGED_REJECTED = "rejete"

# Les colonnes copiées, dans l'ordre de la copie en masse. Nommées une fois : deux listes
# qui divergeraient feraient écrire une empreinte dans la colonne d'un motif de rejet.
_COLUMNS = ("position", "outcome", "cle", "objet", "empreinte", "reason", "detail")

# La table de l'import. Les mêmes contrôles que l'ancienne table permanente, et c'est
# voulu : ce sont des invariants de l'aire, pas des garde-fous de schéma — une ligne « à
# écrire » sans objet, sans empreinte ou sans clé ne doit pas pouvoir exister du tout.
#
# La clé primaire sur `position` n'est pas décorative : la fusion lit l'aire par fenêtres
# de rangs (`position > x AND position <= y`), et sans index chaque fenêtre balaierait
# l'aire entière — cinquante mille items en portent cinq cents.
_CREATE = f"""
CREATE TEMP TABLE {PREPARED_TABLE} (
    position integer PRIMARY KEY CHECK (position >= 0),
    outcome text NOT NULL CHECK (outcome IN ('{STAGED_TO_WRITE}', '{STAGED_REJECTED}')),
    cle text,
    objet jsonb,
    empreinte bytea,
    reason text,
    detail text,
    CHECK ((outcome = '{STAGED_TO_WRITE}')
           = (objet IS NOT NULL AND empreinte IS NOT NULL AND cle IS NOT NULL))
)
"""
_DROP = f"DROP TABLE IF EXISTS pg_temp.{PREPARED_TABLE}"


class PreparedDb(Protocol):
    """Ce que ce module demande à une connexion : de quoi doubler sans monter une base.

    `copy_records_to_table` en fait partie, et c'est assumé : la copie en masse est le
    point du dispositif, et une doublure qui n'aurait que `execute` laisserait croire
    qu'un `INSERT` ferait l'affaire.
    """

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def copy_records_to_table(
        self, table_name: str, *, records: Any, columns: Any
    ) -> str: ...


@dataclass(frozen=True)
class PreparedRow:
    """La MÉTADONNÉE d'un item préparé : son rang, son sort, et son motif de rejet.

    Sans son corps, et c'est le point : la fenêtre d'écriture se lit par ces lignes-là,
    pendant que les objets, eux, vont de l'aire à la table finale SANS remonter jusqu'ici.
    Les relire ferait voyager deux fois cinquante mille documents pour rien.
    """

    position: int
    writable: bool
    key: str | None
    reason: str | None
    detail: str | None


async def db_open_prepared(db: PreparedDb) -> None:
    """Pose la table temporaire de cet import, vide."""
    await db.execute(_DROP)
    await db.execute(_CREATE)


async def db_close_prepared(db: PreparedDb) -> None:
    """Ôte la table temporaire. Rejouable : un import abandonné n'en laisse pas."""
    await db.execute(_DROP)


async def db_copy_prepared(db: PreparedDb, items: list[PreparedObject]) -> None:
    """COPIE EN MASSE un lot d'items préparés. Un lot vide n'écrit rien.

    `COPY` et non `executemany` : l'un écrit un flux binaire que le serveur range sans
    replanifier, l'autre envoie une instruction préparée par ligne. Sur une table
    temporaire, c'est le geste d'écriture le moins cher que PostgreSQL offre.
    """
    if not items:
        return
    await db.copy_records_to_table(
        PREPARED_TABLE,
        records=[
            (
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
        columns=_COLUMNS,
    )


async def db_prepared_window(db: PreparedDb, *, after: int, limit: int) -> list[PreparedRow]:
    """Les métadonnées des items de rang suivant, par rang croissant.

    Par rang croissant, et c'est une règle et non un détail : « deux items de même clé,
    le dernier valide gagne » suppose un ordre d'écriture, et c'est celui du document.
    """
    rows = await db.fetch(
        f"SELECT position, outcome, cle, reason, detail FROM pg_temp.{PREPARED_TABLE}"  # noqa: S608
        " WHERE position > $1 ORDER BY position LIMIT $2",
        after,
        limit,
    )
    return [
        PreparedRow(
            position=int(row["position"]),
            writable=row["outcome"] == STAGED_TO_WRITE,
            key=row["cle"],
            reason=row["reason"],
            detail=row["detail"],
        )
        for row in rows
    ]


async def db_duplicate_keys(db: PreparedDb, *, limit: int) -> list[str]:
    """Les clés portées deux fois ou plus par les items à écrire de cet import.

    En SQL et non en mémoire : tenir l'ensemble des clés d'un document de cinquante mille
    items pendant sa lecture aurait rendu en mémoire ce que la lecture en flux évite. La
    sortie est bornée — on signale une source qui se contredit, on n'en dresse pas
    l'inventaire.
    """
    rows = await db.fetch(
        f"SELECT cle FROM pg_temp.{PREPARED_TABLE}"  # noqa: S608
        " WHERE outcome = $1 AND cle IS NOT NULL"
        " GROUP BY cle HAVING count(*) > 1 ORDER BY min(position) LIMIT $2",
        STAGED_TO_WRITE,
        limit,
    )
    return [row["cle"] for row in rows]
