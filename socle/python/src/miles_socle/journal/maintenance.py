"""L'entretien d'un journal partitionné : poser l'avance, retirer ce qui a expiré.

**Un seul passage fait les deux**, et dans cet ordre. Poser d'abord garantit qu'un
entretien interrompu laisse l'écriture possible ; purger d'abord aurait libéré du disque en
laissant peut-être le journal sans partition du jour.

**Les deux tables du même jour tombent ensemble**, dans la même transaction : la clé
étrangère de `event_objects` vers `events` a dû être retirée pour que la purge soit
possible (mesuré le 03/11/2026 : PostgreSQL refuse de retirer une partition dont une
contrainte dépend), et c'est l'atomicité qui remplace désormais la contrainte — aucun lien
ne survit à l'event qu'il désigne.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import asyncpg
import structlog

from miles_socle.journal.partitions import DAYS_AHEAD, days_to_ensure, expired_days
from miles_socle.journal.store import db_drop_partitions, db_ensure_partitions, db_partition_days

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TableReport:
    table: str
    created: Sequence[date]
    dropped: Sequence[date]
    remaining: int


@dataclass(frozen=True)
class MaintenanceReport:
    day: date
    retention_days: int | None
    tables: Sequence[TableReport]

    @property
    def changed(self) -> bool:
        """Vrai si la base a BOUGÉ.

        Distinct de « l'entretien a tourné » : tout le SQL d'ici est idempotent, donc le
        succès ne dit rien de l'effet. C'est ce qui décide si le journal d'exploitation
        parle (leçon du 02/11/2026).
        """
        return any(t.created or t.dropped for t in self.tables)


@dataclass(frozen=True)
class JournalMaintenance:
    """Entretien des journaux partitionnés d'UNE base.

    `tables` est passée par le produit et non écrite ici : le socle ne porte aucune
    migration, donc il ne sait pas quelles tables un produit a déclarées partitionnées.
    L'ordre compte — les tables dépendantes d'abord, pour qu'une purge interrompue ne
    laisse pas un lien vers un event déjà retiré.
    """

    pool: asyncpg.Pool
    tables: Sequence[str]
    now: Callable[[], datetime]
    # Nombre de jours conservés. **Nul = on ne purge rien** : un paramètre oublié laisse le
    # journal grossir, ce qui se voit et se répare, au lieu de l'effacer sans retour.
    retention_days: int | None = None
    days_ahead: int = DAYS_AHEAD

    async def resolve_maintain(self) -> MaintenanceReport:
        jour = self.now().date()
        a_poser = days_to_ensure(jour, self.days_ahead)
        rapports: list[TableReport] = []
        async with self.pool.acquire() as cnx, cnx.transaction():
            for table in self.tables:
                presentes = await db_partition_days(cnx, table)
                posees = await db_ensure_partitions(cnx, table, a_poser)
                retirees = await db_drop_partitions(
                    cnx, table, expired_days(presentes, jour, self.retention_days)
                )
                restantes = len(presentes | set(posees)) - len(retirees)
                rapports.append(TableReport(table, posees, retirees, restantes))
        rapport = MaintenanceReport(jour, self.retention_days, rapports)
        if rapport.changed:
            log.info(
                "journal_entretenu",
                jour=jour.isoformat(),
                retention_jours=self.retention_days,
                posees={t.table: [j.isoformat() for j in t.created] for t in rapport.tables},
                retirees={t.table: [j.isoformat() for j in t.dropped] for t in rapport.tables},
            )
        return rapport
