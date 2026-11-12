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
from miles_socle.events.model import EventAuthor, EventChecker
from miles_socle.parametrage.sources import Entry

from environnement.hosting.gitstore import HostedTree
from environnement.ingestion.absence import db_mark_absent
from environnement.ingestion.applystaging import (
    FAILURE_APPLY_TOO_LONG,
    ApplyPlan,
    ApplyTooLong,
    resolve_apply,
)
from environnement.ingestion.cleanup import db_remove_designated
from environnement.ingestion.cleanup_rules import CleanupRule, expiry_rule, missing_rule
from environnement.ingestion.files import DepositedFiles
from environnement.ingestion.importtarget import NotImportable, resolve_importable
from environnement.ingestion.jsonflux import STRUCTURAL, DocumentUnreadable
from environnement.ingestion.outcome import (
    ANOMALY_CLEANUP_REFUSED,
    STATE_FAILED,
    STATE_FAILED_IMPORT,
    STATE_PARTIAL,
    STATE_PROCESSED,
    Report,
)
from environnement.ingestion.preparation import PreparedObject, prepare_object
from environnement.ingestion.staging import db_close_prepared, db_copy_prepared, db_open_prepared
from environnement.ingestion.store_imports import (
    ImportJob,
    db_claim_next,
    db_finish_import,
    db_mark_applying,
    db_mark_file_purged,
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
    # Jours de conservation du document déposé. ZÉRO est une configuration VALIDE
    # (critère 20) : le document est alors ôté dès la fin de son import, et aucun rejeu
    # n'est possible sans nouvel export du partenaire. Connue ici et pas seulement de
    # l'entretien, parce que « dès la fin de l'import » ne s'obtient pas en attendant le
    # prochain passage de celui-ci.
    retention_days: int


@dataclass(frozen=True)
class FileImports:
    pool: asyncpg.Pool
    tree: HostedTree
    files: DepositedFiles
    catalog: EventChecker
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
                    # L'instant de la PRISE est nommé ici, et non relu plus tard : c'est
                    # LA MÊME valeur qui part en base sur `started_at` et qui sert de
                    # frontière au marquage des absents. Deux lectures d'horloge auraient
                    # laissé des items du bon côté de l'une et du mauvais côté de l'autre.
                    pris_a = self.now()
                    job = await db_claim_next(conn, storage, pris_a)
                    if job is None:
                        return menes
                    await self.resolve_import(conn, job, started_at=pris_a)
                    menes += 1
            finally:
                # Dans un `finally` : un verrou de SESSION survit à l'exception comme à
                # l'annulation de la tâche, et la connexion rendue au pool le garderait.
                await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", self._key(storage))

    async def resolve_import(self, conn: Any, job: ImportJob, *, started_at: datetime) -> None:
        """Mène un import pris : métadonnées, préparation, écriture, issue.

        `started_at` est l'instant de la prise, celui que la file a écrit sur la ligne.
        Il n'est PAS porté par `ImportJob` : l'entretien relit des imports en cours pour
        les remettre en file, sans jamais les mener, et lui faire porter un instant dont
        il n'a que faire l'aurait rendu nul sur la moitié de ses usages.
        """
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
        try:
            entetes = await asyncio.to_thread(
                file_read_metadata, chemin, keys, self.limits.metadata_budget
            )
        except DocumentUnreadable as refus:
            # La lecture des métadonnées refuse pour les mêmes raisons que la lecture des
            # items — budget dépassé, JSON illisible, découpage introuvable —, et un
            # document illisible est un RÉSULTAT de l'import, pas une panne du service :
            # il s'inscrit sur l'ingestion comme celui que `_stage` découvre plus loin.
            # Laissé sortir, il traversait `resolve_drain` jusqu'à l'entretien, qui rendait
            # 500 ; l'ingestion restait « en cours » sans code de refus, donc reprise
            # toutes les dix minutes, et la purge pour quota ne se faisait plus (bug
            # `572551d7`, mesuré le 07/11/2026).
            log.info("import_document_illisible", ingestion=job.id, code=refus.code, lus=0)
            await self._failed(conn, job, refus.code, refus.detail, 0)
            return
        await db_set_metadata(conn, job.id, entetes)
        await db_open_prepared(conn)
        try:
            lus, incident = await self._stage(conn, job, prepared, cible.entry, chemin, keys)
            await self._write(
                conn, job, cible.entry, prepared, lus, incident, started_at=started_at
            )
        finally:
            # Ôtée quoi qu'il arrive, et pas seulement en sortie heureuse : la connexion
            # revient au pool, et une table laissée derrière ferait écrire les items de ce
            # document dans l'import suivant que la même connexion servira.
            await db_close_prepared(conn)
        await self._purge_now(conn, job)

    async def _purge_now(self, conn: Any, job: ImportJob) -> None:
        """Ôte le document si la rétention est nulle (critère 20).

        Ici et non à l'entretien : « supprimé dès la fin de l'import » est la promesse
        d'une rétention à zéro, et attendre le prochain passage de l'entretien aurait
        laissé le document sur le disque entre-temps — c'est-à-dire aurait fait de zéro
        une durée indéterminée.
        """
        if self.limits.retention_days > 0:
            return
        await self.files.file_remove(job.file_name)
        # Marqué APRÈS le disque : marqué d'abord, un arrêt entre les deux laisserait un
        # fichier que plus rien ne désigne, donc hors de portée de la purge.
        await db_mark_file_purged(conn, job.id, self.now())

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
        gourmands en processeur, et la boucle d'événements sert aussi les écrans. Il est
        ensuite COPIÉ EN MASSE dans la table temporaire de l'import — un flux binaire que
        le serveur range sans replanifier, là où une instruction par item faisait de
        l'écriture le coût dominant d'un document de cinquante mille lignes.
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
            await db_copy_prepared(conn, paquet)
            lus += len(paquet)

    async def _write(
        self,
        conn: Any,
        job: ImportJob,
        entry: Entry,
        prepared: Prepared,
        lus: int,
        incident: tuple[str, str | None] | None,
        *,
        started_at: datetime,
    ) -> None:
        """Écrit l'aire de préparation, ou l'abandonne, et range l'issue de l'import."""
        if incident is not None and (incident[0] in STRUCTURAL or entry.unified_transaction):
            # Deux raisons de n'écrire RIEN, et elles ne se confondent pas :
            #
            # - le document est structurellement inimportable — le découpage ne désigne
            #   rien, ou autre chose qu'un tableau : l'import échoue quelle que soit la
            #   transaction (critère 4), parce qu'aucun item n'a jamais pu être lu ;
            # - la transaction est unifiée : tout ou rien, même sur une interruption au
            #   milieu (critère 7).
            #
            # Dans les deux cas l'aire est abandonnée — l'appelant l'ôte en sortant —, et
            # l'échec dit combien d'items avaient été lus avant l'incident.
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
            await self._failed(conn, job, FAILURE_APPLY_TOO_LONG, str(plan.seconds), lus)
            return
        etat = _state_of(rapport, incident)
        supprimes = None
        if etat == STATE_PROCESSED:
            # LE MARQUAGE DES ABSENTS (Gael, 09/11/2026 : « le déclenchement du nettoyage
            # se traite à la fin de l'import fichier »), et l'endroit n'est pas libre :
            # `traite` SEUL — un import `incomplet` n'a peut-être pas atteint des items
            # qu'il aurait portés ; AVANT `db_finish_import` — une panne du marquage
            # laisse l'ingestion « en cours », que l'entretien remet en file ; et avant
            # que l'appelant n'ôte l'aire de préparation, qui protège les items rejetés.
            # Ce que chaque clause de la sélection tient : `absence.py`.
            await db_mark_absent(conn, prepared.table, started_at=started_at)
            # LE NETTOYAGE, juste après le marquage et pour la même raison qu'il est ici :
            # c'est le moment où l'image est fraîche et où les marques viennent d'être
            # tenues à jour. L'interdit de `9ab435be` — « ne pas déclencher le balayage à
            # la suite d'une ingestion : un import tronqué deviendrait une purge » — ne
            # s'étend pas à ces deux règles, et il faut savoir pourquoi avant d'y toucher :
            # la règle des absents agit N JOURS après une marque qu'un import complet
            # suivant lève (le délai est la protection, et il remplace le verrou), et la
            # péremption ne lit que la donnée de l'objet — un import tronqué n'invente
            # aucune date de fin d'activité.
            supprimes = await db_remove_designated(
                self._processing(conn, job),
                prepared.table,
                _rules(entry, job, prepared),
                now=self.now(),
            )
            if supprimes is None:
                # Le refus se LIT : l'écran des appels montre les anomalies du
                # compte-rendu, et un nettoyage refusé qui ne laisserait qu'une ligne de
                # journal serait invisible à qui regarde l'import.
                rapport.anomalies.append(
                    f"{ANOMALY_CLEANUP_REFUSED}:{','.join(prepared.table.unresolved_expiries)}"
                )
        await db_finish_import(
            conn,
            job.id,
            state=etat,
            report=rapport,
            items_read=lus,
            items_removed=supprimes,
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
                prepared.validator,
                prepared.keys,
                position,
                source,
                limits.transform_budget,
            )
        )
        if len(paquet) >= taille:
            break
    return paquet


def _rules(entry: Entry, job: ImportJob, prepared: Prepared) -> list[CleanupRule]:
    """Les règles de nettoyage qui valent pour CET import : l'entrée, puis le storage.

    Les deux viennent de la version servie, jamais du code : le délai est une valeur de
    la déclaration (interdit du ticket). Une entrée sans règle et un storage sans
    péremption donnent une liste vide, et rien n'est supprimé — c'est le défaut.

    La règle des absents vient de l'ENTRÉE parce qu'elle n'a de sens que relativement à un
    dépôt qui prétend porter l'image complète ; on est ici dans un import de fichier, donc
    exactement dans ce cas.
    """
    regles: list[CleanupRule] = []
    if entry.missing_removed_after_days is not None:
        regles.append(missing_rule(entry.missing_removed_after_days, job.source))
    return regles + [expiry_rule(rule) for rule in prepared.table.expiries]


def _state_of(report: Report, incident: tuple[str, str | None] | None) -> str:
    """L'état final : incomplet si le document s'est interrompu, sinon l'issue du lot.

    « incomplet » prime sur « traite » et sur « rejete » : c'est l'état que le balayage
    refuse, et le confondre avec un import réussi ferait sortir du storage des objets que
    le document n'avait simplement pas eu le temps de nommer.
    """
    if incident is not None:
        return STATE_PARTIAL
    return STATE_FAILED if report.all_rejected else STATE_PROCESSED
