"""Les partitions réellement en base, posées et retirées.

Ce module LIT le catalogue de PostgreSQL plutôt que de supposer ce qu'une migration a
posé : c'est la seule source qui dise ce qui existe vraiment, et la purge ne doit jamais
retirer ce qu'elle n'a pas vu.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import structlog

from miles_socle.journal.partitions import create_partition, drop_partition, partition_day

log = structlog.get_logger(__name__)


class JournalDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


# `relkind = 'p'` filtre la table PARTITIONNÉE : interroger `pg_inherits` sur une table
# ordinaire rendrait ses éventuelles tables héritées, qui ne sont pas des partitions.
_PARTITIONS = """
SELECT c.relname AS nom
FROM pg_class parent
JOIN pg_inherits i ON i.inhparent = parent.oid
JOIN pg_class c ON c.oid = i.inhrelid
WHERE parent.relname = $1 AND parent.relkind = 'p'
"""

_EST_PARTITIONNEE = "SELECT relkind = 'p' AS partitionnee FROM pg_class WHERE relname = $1"


async def db_partitioned(db: JournalDb, table: str) -> bool:
    """Vrai si cette table est partitionnée. Nul retour n'est pas « non » : table absente."""
    rows = await db.fetch(_EST_PARTITIONNEE, table)
    return bool(rows) and bool(rows[0]["partitionnee"])


async def db_partition_days(db: JournalDb, table: str) -> set[date]:
    """Les jours que les partitions de cette table portent.

    Une partition dont le nom n'est pas le nôtre est **ignorée** et non rendue : la purge
    ne retire que ce qu'elle sait avoir posé. Quelqu'un qui attache une partition à la main
    la garde, et aucun entretien ne la lui enlève.
    """
    rows = await db.fetch(_PARTITIONS, table)
    jours = {partition_day(table, row["nom"]) for row in rows}
    return {jour for jour in jours if jour is not None}


async def db_ensure_partitions(db: JournalDb, table: str, days: list[date]) -> list[date]:
    """Pose les partitions manquantes, et rend celles qui ont été réellement CRÉÉES.

    L'écart est lu dans le catalogue avant d'écrire, et non déduit du succès des `CREATE` :
    `IF NOT EXISTS` réussit aussi quand il n'a rien fait, et le journal d'exploitation
    annoncerait alors une pose à chaque passage (leçon du 02/11/2026 sur les opérations
    idempotentes qui ne savent pas si elles ont agi).
    """
    presentes = await db_partition_days(db, table)
    manquantes = [jour for jour in days if jour not in presentes]
    for jour in manquantes:
        await db.execute(create_partition(table, jour))
    return manquantes


async def db_drop_partitions(db: JournalDb, table: str, days: list[date]) -> list[date]:
    """Retire ces partitions, et rend celles qui existaient vraiment."""
    presentes = await db_partition_days(db, table)
    retirees = [jour for jour in days if jour in presentes]
    for jour in retirees:
        await db.execute(drop_partition(table, jour))
    return retirees
