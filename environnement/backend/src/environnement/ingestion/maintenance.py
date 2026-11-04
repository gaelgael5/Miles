"""L'entretien des imports : rattraper les interrompus, purger les documents conservés.

Appelé par un déclencheur d'HÔTE, comme l'entretien des journaux partitionnés (décision de
Gael du 03/11/2026, entre quatre pistes) : l'entretien au démarrage ne purge plus quand une
stack tourne longtemps, et une boucle de fond rouvre la question du multi-instance.

**Quatre gestes, dans cet ordre, et l'ordre est la garantie :**

1. les imports ORPHELINS — déclarés en cours alors que personne ne les mène — retournent en
   file, ou tombent en échec si leur document n'est plus là (critère 14) ;
2. les documents EXPIRÉS sont purgés, par ancienneté (critère 16) ;
3. si le quota reste dépassé, on purge encore, toujours du plus ancien au plus récent, et
   JAMAIS un document dont l'import est en file ou en cours (critère 17) ;
4. les fichiers SANS LIGNE sont ôtés : ce sont ceux d'un dépôt arrêté entre l'écriture du
   document et son inscription, et le fichier temporaire ne doit pas fuir (critère 14).

La file est drainée en dernier, comme rattrapage : un dépôt arrivé juste après la dernière
vérification de la file d'un import en cours attendrait sinon le dépôt suivant.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import structlog

from environnement.ingestion.fileimport import FAILURE_FILE_MISSING, LOCK_PREFIX
from environnement.ingestion.files import DepositedFiles
from environnement.ingestion.outcome import STATE_FAILED_IMPORT
from environnement.ingestion.store_imports import (
    KeptFile,
    db_finish_import,
    db_kept_files,
    db_mark_file_purged,
    db_queued_storages,
    db_requeue,
    db_running_imports,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ImportsMaintenanceReport:
    """Ce que l'entretien a fait. Des COMPTES, pas un code de retour : « c'est passé » ne
    dit pas si la base a bougé."""

    requeued: int
    failed: int
    purged_expired: int
    purged_for_quota: int
    orphan_files_removed: int
    drained: int
    used_bytes: int

    @property
    def changed(self) -> bool:
        return bool(
            self.requeued
            or self.failed
            or self.purged_expired
            or self.purged_for_quota
            or self.orphan_files_removed
            or self.drained
        )


@dataclass(frozen=True)
class ImportsMaintenance:
    pool: asyncpg.Pool
    files: DepositedFiles
    now: Callable[[], datetime]
    # Jours de conservation d'un document déposé. ZÉRO EST VALIDE (critère 20) : le
    # document est alors purgé dès la fin de son import, et aucun rejeu n'est possible
    # sans nouvel export du partenaire.
    retention_days: int
    drain: Callable[[str], Awaitable[int]]
    # Verrou consultatif à tenter pour savoir si un import est VRAIMENT mené. Injecté
    # pour que les tests mesurent la même chose que la production.
    lock_key: Callable[[str], str] = field(default=lambda storage: f"{LOCK_PREFIX}{storage}")

    async def resolve_maintain(self) -> ImportsMaintenanceReport:
        """Fait les quatre gestes, puis draine la file, et rend ses comptes."""
        async with self.pool.acquire() as conn:
            repris, echoues = await self._recover(conn)
            expires = await self._purge_expired(conn)
            quota = await self._purge_for_quota(conn)
            orphelins = await self._remove_orphans(conn)
            storages = await db_queued_storages(conn)
        menes = 0
        for storage in storages:
            menes += await self.drain(storage)
        rapport = ImportsMaintenanceReport(
            requeued=repris,
            failed=echoues,
            purged_expired=expires,
            purged_for_quota=quota,
            orphan_files_removed=orphelins,
            drained=menes,
            used_bytes=await self.files.file_used_bytes(),
        )
        log.info(
            "entretien_des_imports",
            repris=rapport.requeued,
            echoues=rapport.failed,
            purges=rapport.purged_expired + rapport.purged_for_quota,
            orphelins=rapport.orphan_files_removed,
            menes=rapport.drained,
        )
        return rapport

    async def _recover(self, conn: Any) -> tuple[int, int]:
        """Les imports déclarés en cours que personne ne mène (critère 14).

        **Comment on sait que personne ne les mène** : le verrou du storage est LIBRE. Un
        import qui tourne le tient, et le verrou vit dans la base — donc le constat vaut
        aussi quand c'est une autre instance qui mène l'import. On le prend puis on le
        rend tout de suite : le prendre est la mesure.
        """
        repris = echoues = 0
        # Le disque est listé UNE fois : une liste par import orphelin aurait fait un
        # parcours de répertoire par ligne, pour une réponse qui ne change pas ici.
        presents = await self.files.file_names()
        for job in await db_running_imports(conn):
            if not await self._free(conn, job.storage):
                continue
            if job.file_name not in presents:
                # Le document n'est plus là : l'import n'est pas rejouable, et il tombe en
                # échec plutôt que de rester dans un état indéterminé.
                await db_finish_import(
                    conn,
                    job.id,
                    state=STATE_FAILED_IMPORT,
                    report=None,
                    items_read=0,
                    now=self.now(),
                    failure_code=FAILURE_FILE_MISSING,
                    failure_detail=job.file_name,
                )
                echoues += 1
                continue
            if await db_requeue(conn, job.id):
                repris += 1
        return repris, echoues

    async def _free(self, conn: Any, storage: str) -> bool:
        cle = self.lock_key(storage)
        pris = await conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", cle)
        if pris:
            await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", cle)
        return bool(pris)

    async def _purge_expired(self, conn: Any) -> int:
        """Purge ce qui a dépassé la durée de conservation. L'historique RESTE."""
        limite = self.now() - timedelta(days=self.retention_days)
        purges = 0
        for garde in await db_kept_files(conn):
            if garde.busy or garde.received_at > limite:
                continue
            await self._purge(conn, garde)
            purges += 1
        return purges

    async def _purge_for_quota(self, conn: Any) -> int:
        """Purge du plus ancien au plus récent tant que le quota est dépassé.

        **Jamais un document dont l'import est en file ou en cours**, même sous pression :
        le purger ferait échouer un import qui, lui, est légitime. Si le quota reste
        dépassé après cette purge, ce sont les nouveaux dépôts qui sont refusés — un
        refus explicite valant mieux qu'un import tombé au milieu (critère 17).
        """
        occupe = await self.files.file_used_bytes()
        if occupe <= self.files.quota_bytes:
            return 0
        purges = 0
        for garde in await db_kept_files(conn):
            if occupe <= self.files.quota_bytes:
                break
            if garde.busy:
                continue
            await self._purge(conn, garde)
            occupe -= garde.size_bytes
            purges += 1
        return purges

    async def _purge(self, conn: Any, garde: KeptFile) -> None:
        await self.files.file_remove(garde.file_name)
        # La ligne est marquée APRÈS le disque : marquée d'abord, un arrêt entre les deux
        # laisserait un fichier que plus rien ne désigne, donc hors de portée de la purge.
        await db_mark_file_purged(conn, garde.ingestion_id, self.now())

    async def _remove_orphans(self, conn: Any) -> int:
        """Ôte les fichiers que plus aucune ligne ne réclame."""
        connus = {garde.file_name for garde in await db_kept_files(conn)}
        otes = 0
        for nom in await self.files.file_names():
            if nom in connus:
                continue
            log.warning("fichier_orphelin_ote", nom=nom)
            if await self.files.file_remove(nom):
                otes += 1
        return otes
