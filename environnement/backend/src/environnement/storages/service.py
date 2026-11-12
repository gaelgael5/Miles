"""Matérialiser les tables de la version servie, et dire ce qui s'est passé.

Appelé quand l'arbre vient de changer, et rejouable à volonté : l'opération se DÉDUIT de
l'écart entre ce que le catalogue porte et ce que la version déclare. Rien n'y est
incrémental, donc rien n'y dépend de l'ordre dans lequel les versions sont passées — un
volume restauré, une base recréée, un ordre rejoué donnent le même résultat.

**Ce qui se supprime, et ce qui ne se supprime jamais.** Une colonne DÉRIVÉE se retire
sans perte : elle est une fonction de `objet`, et PostgreSQL la recalcule à l'identique si
on la remet. Une table, une colonne de données, un index posé par quelqu'un d'autre : on
n'y touche pas, et un écart constaté se signale au lieu d'être réparé.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventChecker, NewEvent, ObjectRef

from environnement.hosting.gitstore import HostedTree
from environnement.storages.ddl import (
    IdentifierError,
    rewrites_table,
    statements_for,
)
from environnement.storages.declarations import Declared, file_declared
from environnement.storages.model import (
    REFUSAL_APPLY_FAILED,
    REFUSAL_BAD_NAME,
    REFUSAL_UNEXPECTED_SHAPE,
    STORAGE_REFUSED_EVENT,
    STORAGES_MATERIALISED_EVENT,
    STORAGES_OBJECT_KIND,
    StorageRefusal,
    StorageTable,
)
from environnement.storages.plan import alignment, missing_fixed
from environnement.storages.query import Query
from environnement.storages.store import (
    Materialised,
    StorageDb,
    db_existing_table,
    db_forget,
    db_materialised,
    db_record_applied,
    db_record_refusal,
)

log = structlog.get_logger(__name__)
# L'auteur des matérialisations : ce n'est personne, c'est la pose d'une version. Le
# journal doit pouvoir le dire sans emprunter l'identité de qui a ordonné la version chez
# l'enrôlement — ce n'est pas lui qui a écrit ce SQL.
SYSTEM_AUTHOR = EventAuthor("local", "stack")


@dataclass(frozen=True)
class Outcome:
    """Ce qu'une matérialisation a produit.

    `applied` et `changed` ne se confondent pas, et la campagne d'intégration a montré
    pourquoi : à chaque pose, TOUS les storages déclarés sont « appliqués » — leur SQL
    est rejoué, sans effet. Seul `changed` dit que la base a bougé, et c'est lui qui
    décide si le journal parle. Sans cette distinction, un ordre rejoué écrivait un event
    affirmant qu'on venait de matérialiser deux tables déjà en place.
    """

    applied: tuple[str, ...]
    changed: tuple[str, ...]
    refused: tuple[StorageRefusal, ...]
    forgotten: tuple[str, ...]


@dataclass(frozen=True)
class StoragesService:
    pool: asyncpg.Pool
    tree: HostedTree
    catalog: EventChecker
    now: Callable[[], datetime]

    async def resolve_materialise(self, version_number: int) -> Outcome:
        """Aligne la base sur la version servie. Idempotent."""
        declared = await self.resolve_declared()
        applied: list[str] = []
        changed: list[str] = []
        refused: list[StorageRefusal] = list(declared.refusals)
        for table in declared.tables:
            refus, bouge = await self._one(table, version_number)
            if refus is not None:
                refused.append(refus)
                continue
            applied.append(table.storage)
            if bouge:
                changed.append(table.storage)
        async with self.pool.acquire() as conn, conn.transaction():
            for refus in declared.refusals:
                await db_record_refusal(conn, refus)
            noms = [t.storage for t in declared.tables] + [r.storage for r in refused]
            forgotten = await db_forget(conn, noms)
        outcome = Outcome(tuple(applied), tuple(changed), tuple(refused), tuple(forgotten))
        await self._journalise(version_number, outcome)
        return outcome

    async def resolve_declared(self) -> Declared:
        """Les déclarations de la version servie, telles que l'arbre les porte.

        Relues à chaque appel, et non mises en cache : l'arbre change quand une
        version est servie, et un cache invalidé par un autre chemin que celui-là
        aurait un jour montré les storages d'une version qui n'est plus là.
        """
        return await file_declared(self.tree.file_text, await self.tree.file_paths())

    async def resolve_search(self, requete: Query) -> tuple[list[Any], int]:
        """Les objets et leur compte, sur la MÊME clause : une seule transaction.

        La même transaction, parce qu'un total compté hors d'elle pourrait annoncer
        un nombre de pages que la liste ne porte pas.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(requete.sql, *requete.values)
            total = await conn.fetchval(requete.count_sql, *requete.values)
        return list(rows), int(total or 0)

    async def resolve_designated(
        self, page_sql: str, count_sql: str, *, threshold: Any, limit: int, offset: int
    ) -> tuple[list[Any], int]:
        """La page de ce qu'une règle de nettoyage désignerait, et son compte. Ne supprime rien.

        À part de `resolve_search` parce que les deux instructions ne prennent pas les
        mêmes paramètres : la page est bornée, le compte ne l'est pas, et asyncpg refuse
        une requête à qui l'on passe un argument de plus qu'elle n'en attend. La MÊME
        transaction, pour la même raison qu'à la recherche — un total compté dehors
        annoncerait des pages que la liste ne porte pas, et un import peut nettoyer
        pendant qu'on regarde.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(page_sql, threshold, limit, offset)
            total = await conn.fetchval(count_sql, threshold)
        return list(rows), int(total or 0)

    async def resolve_lag(self, table: StorageTable) -> tuple[str, ...] | None:
        """Ce que la table n'a pas encore de ce que la version servie déclare.

        None : la table n'existe pas du tout. Un tuple vide : elle est à jour.

        Lire une table d'après une déclaration qu'elle ne porte pas encore donne une
        erreur SQL brute et un 500 — c'est arrivé le 05/11/2026, le jour où le MODÈLE a
        commencé à déclarer des colonnes : la déclaration change avec la version servie,
        la table ne change qu'à la POSE d'une version, et entre les deux la lecture
        tombait sur « column "prop_id" does not exist ». Un écart entre ce qu'on déclare
        et ce qui est posé est un état NORMAL et transitoire du système : il se dit,
        avec le geste qui le referme, il ne se plante pas.
        """
        async with self.pool.acquire() as conn:
            existing = await db_existing_table(conn, table.schema, table.table)
        if existing is None:
            return None
        return tuple(p.column for p in table.projections if existing.column(p.column) is None)

    async def resolve_state(self) -> list[Materialised]:
        async with self.pool.acquire() as conn:
            return await db_materialised(conn)

    async def resolve_preview(self) -> dict[str, list[str]]:
        """Le SQL que la version servie produirait, sans rien appliquer.

        La contrepartie de l'absence d'homologation : personne ne relit ce DDL avant qu'il
        s'applique, donc il doit au moins être lisible avant et après.
        """
        declared = await self.resolve_declared()
        preview: dict[str, list[str]] = {}
        for table in declared.tables:
            try:
                # `statements_for` porte DÉJÀ les index : les rajouter affichait chaque
                # index déclaré deux fois, et un aperçu qui se répète fait douter de ce
                # qui sera réellement exécuté. Vu en passant le paramétrage réel de
                # Gael dans le résolveur, le 02/11/2026.
                preview[table.storage] = statements_for(table)
            except IdentifierError as refuse:
                preview[table.storage] = [f"-- refusé : nom invalide ({refuse.name})"]
        return preview

    async def _one(
        self, table: StorageTable, version_number: int
    ) -> tuple[StorageRefusal | None, bool]:
        """Pose ou aligne UNE table. Rend (le refus ou nul, la base a-t-elle bougé).

        Chaque storage a sa transaction : un refus sur l'un laisse les autres posés, et
        c'est voulu — une version qui déclare un storage fautif ne doit pas priver
        l'environnement de ceux qui sont justes.
        """
        try:
            plan = await self._plan(table)
        except IdentifierError as refuse:
            return StorageRefusal(table.storage, REFUSAL_BAD_NAME, refuse.name), False
        if isinstance(plan, StorageRefusal):
            async with self.pool.acquire() as conn, conn.transaction():
                await db_record_refusal(conn, plan)
            return plan, False
        instructions, bouge = plan
        # Dit AVANT de l'exécuter : l'ajout d'une colonne dérivée réécrit la table sous
        # verrou exclusif, donc le storage est illisible le temps de l'opération. Le DDL
        # appliqué est déjà rangé en base par `db_record_applied`, mais une trace qu'on
        # relit après coup n'aide pas celui qui regarde un déploiement en cours.
        reecritures = [i for i in instructions if rewrites_table(i)]
        if reecritures:
            log.warning(
                "table_de_storage_reecrite_sous_verrou",
                storage=table.storage,
                colonnes=len(reecritures),
            )
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                for instruction in instructions:
                    await conn.execute(instruction)
                await db_record_applied(conn, table, version_number, instructions, self.now())
        except asyncpg.PostgresError as panne:
            # Le motif de PostgreSQL, pas un message maison : c'est lui qui dira pourquoi,
            # et le reformuler ferait perdre la seule information utile.
            log.warning("table_de_storage_non_posee", storage=table.storage, reason=str(panne))
            refus = StorageRefusal(table.storage, REFUSAL_APPLY_FAILED, str(panne)[:300])
            async with self.pool.acquire() as conn, conn.transaction():
                await db_record_refusal(conn, refus)
            return refus, False
        return None, bouge

    async def _plan(self, table: StorageTable) -> tuple[list[str], bool] | StorageRefusal:
        """Le SQL à exécuter, et si son exécution va changer quelque chose.

        Le second terme ne se déduit PAS du SQL : tout y est en `if not exists`, donc le
        texte d'une pose et celui d'un rejeu sont identiques. Il se déduit de l'écart avec
        le catalogue, et c'est le seul endroit où on le connaisse.
        """
        async with self.pool.acquire() as conn:
            existing = await db_existing_table(conn, table.schema, table.table)
        if existing is None:
            return statements_for(table), True
        manquante = missing_fixed(existing)
        if manquante is not None:
            # Signalé, jamais réparé en silence : une table de ce nom existe et n'a pas
            # la forme d'une table de storage. La réparer supposerait de savoir ce
            # qu'elle porte, et on ne le sait pas.
            return StorageRefusal(table.storage, REFUSAL_UNEXPECTED_SHAPE, manquante)
        return alignment(table, existing)

    async def _journalise(self, version_number: int, outcome: Outcome) -> None:
        if not outcome.changed and not outcome.refused and not outcome.forgotten:
            # Rien ne s'est passé : le journal ne doit pas dire le contraire. Même règle
            # que pour un ordre de version rejoué sur un arbre conforme.
            return
        async with self.pool.acquire() as conn, conn.transaction():
            await self._event(
                conn,
                STORAGES_MATERIALISED_EVENT,
                {
                    "version": version_number,
                    # Ce qui a CHANGÉ, pas ce qui est en place : un journal qui annonce
                    # une pose à chaque rejeu ne se lit plus.
                    "changed": list(outcome.changed),
                    "refused": [r.storage for r in outcome.refused],
                    "forgotten": list(outcome.forgotten),
                },
            )
            for refus in outcome.refused:
                await self._event(
                    conn,
                    STORAGE_REFUSED_EVENT,
                    {
                        "version": version_number,
                        "storage": refus.storage,
                        "refusal": refus.code,
                        "detail": refus.detail,
                    },
                )
        log.info(
            "storages_materialises",
            version=version_number,
            applied=len(outcome.applied),
            refused=len(outcome.refused),
        )

    async def _event(self, conn: StorageDb, kind: str, properties: dict[str, Any]) -> None:
        event = NewEvent(
            kind, (ObjectRef(STORAGES_OBJECT_KIND, "self"),), SYSTEM_AUTHOR, properties
        )
        await db_write_event(conn, event, self.catalog, self.now)
