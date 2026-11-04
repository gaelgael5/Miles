"""Mener un import de fichier : préparer HORS transaction, puis écrire. Story `0f14adbd`.

**L'import est asynchrone**, parce que le contrat publié ne promet au mode `fichier` qu'un
« acquittement de prise en charge ». Le dépôt pose le document sur le disque et met l'import
en file ; c'est ici qu'il se déroule, plus tard, et son issue se lit dans l'historique des
ingestions.

**Un seul import à la fois par STORAGE** (critère 12), tenu par un verrou consultatif de
PostgreSQL et non par un verrou de processus : deux instances de la stack frapperaient la
même table, et un verrou en mémoire n'en aurait rien su. Le storage et non la source : deux
sources peuvent alimenter le même storage, et leurs imports ne doivent pas s'y croiser.

**Trois phases, et l'ordre porte toutes les garanties** : les métadonnées (première passe,
critère 6), la préparation item par item dans l'aire de préparation (hors transaction), puis
l'écriture (transaction courte). Une interruption entre deux phases laisse l'import en
cours, et l'entretien le remet en file — rejouer est sûr parce que l'écriture est
différentielle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog
from miles_socle.apikeys.model import KEY_DIRECTORY
from miles_socle.events.model import EventAuthor, EventTypeCatalog
from miles_socle.parametrage.sources import Entry

from environnement.hosting.gitstore import HostedTree
from environnement.ingestion.applystaging import (
    FAILURE_APPLY_TOO_LONG,
    ApplyPlan,
    ApplyTooLong,
    resolve_apply,
)
from environnement.ingestion.files import DepositedFiles
from environnement.ingestion.importtarget import NotImportable, resolve_importable
from environnement.ingestion.jsonflux import DocumentUnreadable
from environnement.ingestion.outcome import (
    STATE_FAILED,
    STATE_FAILED_IMPORT,
    STATE_PARTIAL,
    STATE_PROCESSED,
    Report,
)
from environnement.ingestion.preparation import PreparedObject, prepare_object
from environnement.ingestion.staging import db_clear_staging, db_stage
from environnement.ingestion.store_imports import (
    ImportJob,
    db_claim_next,
    db_finish_import,
    db_mark_applying,
    db_set_metadata,
)
from environnement.ingestion.stream import file_iter_items, file_read_metadata
from environnement.ingestion.writeback import Prepared, Processing

log = structlog.get_logger(__name__)

# Le verrou qui sérialise les imports d'un storage. Préfixé pour que la valeur hachée ne
# puisse pas rencontrer celle d'un autre verrou du dépôt — celui des migrations, celui de
# l'appariement. Une collision ne corromprait rien : elle ferait attendre un import
# derrière un geste sans rapport, et c'est pourquoi on la rend improbable plutôt que de
# s'en remettre au hasard.
LOCK_PREFIX = "ingestion-import:"

# Pourquoi un import n'a pas abouti. Chacun dit un geste différent, et aucun ne se devine
# depuis « échec ».
FAILURE_FILE_MISSING = "fichier_absent"


@dataclass(frozen=True)
class ImportLimits:
    """Les bornes d'exploitation d'un import. Toutes paramétrables : ce sont des décisions
    d'exploitation, pas des limites techniques."""

    metadata_budget: int
    apply_seconds: float
    detail_cap: int
    transform_budget: int


@dataclass(frozen=True)
class FileImports:
    pool: asyncpg.Pool
    tree: HostedTree
    files: DepositedFiles
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    limits: ImportLimits

    async def resolve_drain(self, storage: str) -> int:
        """Mène les imports en file sur ce storage, un par un, et rend leur nombre.

        **Rend zéro sans rien faire si un autre import tourne déjà sur ce storage** : le
        second n'est pas perdu, il reste en file, et c'est celui qui tient le verrou qui le
        prendra en sortant de sa boucle. Un dépôt arrivé juste après la dernière vérification
        de la file attendrait le prochain entretien, qui est le rattrapage prévu pour cela.
        """
        async with self.pool.acquire() as conn:
            pris = await conn.fetchval(
                "SELECT pg_try_advisory_lock(hashtext($1))", self._key(storage)
            )
            if not pris:
                log.info("import_deja_en_cours", storage=storage)
                return 0
            try:
                menes = 0
                while True:
                    job = await db_claim_next(conn, storage, self.now())
                    if job is None:
                        return menes
                    await self.resolve_import(conn, job)
                    menes += 1
            finally:
                # Dans un `finally` : un verrou de SESSION survit à l'exception comme à
                # l'annulation de la tâche, et la connexion rendue au pool le garderait.
                await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", self._key(storage))

    async def resolve_import(self, conn: Any, job: ImportJob) -> None:
        """Mène un import pris : métadonnées, préparation, écriture, issue."""
        chemin = self.files.file_path(job.file_name)
        if not chemin.exists():
            # Le document a été purgé ou n'a jamais été posé : l'import ne peut plus être
            # mené, et il est marqué en échec plutôt que laissé en cours (critère 14).
            await self._failed(conn, job, FAILURE_FILE_MISSING, job.file_name, 0)
            return
        try:
            lu = await resolve_importable(self.pool, self.tree, job)
        except NotImportable as refus:
            await self._failed(conn, job, refus.code, refus.detail, 0)
            return
        cible, prepared, keys = lu.target, lu.prepared, lu.keys
        await db_set_metadata(
            conn,
            job.id,
            await asyncio.to_thread(file_read_metadata, chemin, keys, self.limits.metadata_budget),
        )
        lus, incident = await self._stage(conn, job, prepared, cible.entry, chemin, keys)
        await self._write(conn, job, cible.entry, prepared, lus, incident)

    async def _stage(
        self,
        conn: Any,
        job: ImportJob,
        prepared: Prepared,
        entry: Entry,
        chemin: Path,
        keys: tuple[str | int, ...],
    ) -> tuple[int, tuple[str, str | None] | None]:
        """Lit, transforme et range les items. Rend le nombre lu et l'incident éventuel.

        **Rien de tout cela n'est dans une transaction**, et c'est l'interdit du ticket :
        l'évaluation du template item par item est le temps long d'un import, et une
        transaction qui l'englobe empêche autovacuum de nettoyer la table visée.

        Chaque paquet est lu ET transformé dans un FIL : les deux sont bloquants et
        gourmands en processeur, et la boucle d'événements sert aussi les écrans.
        """
        items = file_iter_items(chemin, keys)
        lus = 0
        while True:
            try:
                paquet = await asyncio.to_thread(
                    _prepared_batch, items, prepared, lus, entry.write_batch, self.limits
                )
            except DocumentUnreadable as refus:
                # Les items déjà rangés restent : ce qu'on en fait dépend de la transaction
                # unifiée (critères 7 et 8), et c'est l'écriture qui tranche.
                log.info("import_document_illisible", ingestion=job.id, code=refus.code, lus=lus)
                return lus, (refus.code, refus.detail)
            if not paquet:
                return lus, None
            await db_stage(conn, job.id, paquet)
            lus += len(paquet)

    async def _write(
        self,
        conn: Any,
        job: ImportJob,
        entry: Entry,
        prepared: Prepared,
        lus: int,
        incident: tuple[str, str | None] | None,
    ) -> None:
        """Écrit l'aire de préparation, ou l'abandonne, et range l'issue de l'import."""
        if incident is not None and entry.unified_transaction:
            # Tout ou rien : rien n'est écrit dans le storage — ni corps, ni date de
            # dernière vue —, l'aire est abandonnée, et l'échec dit combien d'items
            # avaient été lus avant l'incident (critère 7).
            await db_clear_staging(conn, job.id)
            await self._failed(conn, job, incident[0], incident[1], lus)
            return
        plan = ApplyPlan(
            unified=entry.unified_transaction,
            write_batch=entry.write_batch,
            seconds=self.limits.apply_seconds,
            detail_cap=self.limits.detail_cap,
        )
        await db_mark_applying(conn, job.id, self.now())
        try:
            rapport = await resolve_apply(conn, self._processing(conn, job), prepared, plan)
        except ApplyTooLong:
            await db_clear_staging(conn, job.id)
            await self._failed(conn, job, FAILURE_APPLY_TOO_LONG, str(plan.seconds), lus)
            return
        await db_clear_staging(conn, job.id)
        await db_finish_import(
            conn,
            job.id,
            state=_state_of(rapport, incident),
            report=rapport,
            items_read=lus,
            now=self.now(),
            failure_code=None if incident is None else incident[0],
            failure_detail=None if incident is None else incident[1],
        )

    async def _failed(
        self, conn: Any, job: ImportJob, code: str, detail: str | None, lus: int
    ) -> None:
        log.warning("import_en_echec", ingestion=job.id, code=code, detail=detail, lus=lus)
        await db_finish_import(
            conn,
            job.id,
            state=STATE_FAILED_IMPORT,
            report=None,
            items_read=lus,
            now=self.now(),
            failure_code=code,
            failure_detail=detail,
        )

    def _processing(self, conn: Any, job: ImportJob) -> Processing:
        # L'auteur des events est la CLÉ qui a déposé, jamais une personne : c'est elle qui
        # a fourni le document, et l'import n'est que son exécution différée.
        return Processing(
            db=conn,
            catalog=self.catalog,
            now=self.now,
            budget=self.limits.transform_budget,
            author=EventAuthor(KEY_DIRECTORY, job.key_id),
            ingestion_id=job.id,
            model_version=job.version_number,
        )

    def _key(self, storage: str) -> str:
        return f"{LOCK_PREFIX}{storage}"


def _prepared_batch(
    items: Any, prepared: Prepared, deja: int, taille: int, limits: ImportLimits
) -> list[PreparedObject]:
    """Lit `taille` items et les prépare. BLOQUANT : appelé dans un fil.

    Le générateur est repris d'un appel à l'autre, et c'est sans danger bien que les fils
    puissent différer : les appels sont séquentiels — un `await` les sépare —, donc jamais
    deux ne le parcourent en même temps.
    """
    paquet: list[PreparedObject] = []
    for position, source in enumerate(items, start=deja):
        paquet.append(
            prepare_object(
                prepared.chain,
                prepared.schema,
                prepared.table.keys,
                position,
                source,
                limits.transform_budget,
            )
        )
        if len(paquet) >= taille:
            break
    return paquet


def _state_of(report: Report, incident: tuple[str, str | None] | None) -> str:
    """L'état final : incomplet si le document s'est interrompu, sinon l'issue du lot.

    « incomplet » prime sur « traite » et sur « rejete » : c'est l'état que le balayage
    refuse, et le confondre avec un import réussi ferait sortir du storage des objets que
    le document n'avait simplement pas eu le temps de nommer.
    """
    if incident is not None:
        return STATE_PARTIAL
    return STATE_FAILED if report.all_rejected else STATE_PROCESSED
