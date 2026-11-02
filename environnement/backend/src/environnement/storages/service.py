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
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from environnement.hosting.gitstore import HostedTree
from environnement.storages.ddl import (
    KEY_INDEX,
    IdentifierError,
    add_column,
    create_indexes,
    drop_column,
    drop_index,
    index_name,
    is_ours,
    statements_for,
)
from environnement.storages.declarations import Declared, file_declared
from environnement.storages.model import (
    FIXED_COLUMNS,
    REFUSAL_APPLY_FAILED,
    REFUSAL_BAD_NAME,
    REFUSAL_TYPE_CHANGE,
    REFUSAL_UNEXPECTED_SHAPE,
    STORAGE_REFUSED_EVENT,
    STORAGES_MATERIALISED_EVENT,
    STORAGES_OBJECT_KIND,
    StorageRefusal,
    StorageTable,
)
from environnement.storages.query import Query
from environnement.storages.store import (
    ExistingTable,
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
    catalog: EventTypeCatalog
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
                preview[table.storage] = statements_for(table) + create_indexes(table)[1:]
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
        manquante = _missing_fixed(existing)
        if manquante is not None:
            # Signalé, jamais réparé en silence : une table de ce nom existe et n'a pas
            # la forme d'une table de storage. La réparer supposerait de savoir ce
            # qu'elle porte, et on ne le sait pas.
            return StorageRefusal(table.storage, REFUSAL_UNEXPECTED_SHAPE, manquante)
        return _alignment(table, existing)

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


def _missing_fixed(existing: ExistingTable) -> str | None:
    """Le nom de la première colonne fixe absente ou mal typée. Nul si la forme tient."""
    for name, sql_type in FIXED_COLUMNS:
        column = existing.column(name)
        if column is None:
            return name
        if column.sql_type != sql_type:
            return f"{name}:{column.sql_type}"
    return None


def _alignment(
    table: StorageTable, existing: ExistingTable
) -> tuple[list[str], bool] | StorageRefusal:
    """Ce qu'il faut faire pour que la table porte ce que la version déclare."""
    instructions: list[str] = []
    voulues = {p.column: p for p in table.projections}
    for projection in table.projections:
        column = existing.column(projection.column)
        if column is None:
            instructions.append(add_column(table, projection))
            continue
        if not column.generated:
            # Une colonne de DONNÉES porte ce nom. On ne la remplace pas : elle pourrait
            # porter de la donnée propre, que la dérivation écraserait sans retour.
            return StorageRefusal(table.storage, REFUSAL_UNEXPECTED_SHAPE, projection.column)
        if column.sql_type != projection.sql_type:
            # Changer le type d'une colonne dérivée réécrit la table sous verrou. Le coût
            # n'a pas été mesuré : on s'arrête et on le dit, plutôt que de le payer à
            # l'insu de qui déploie.
            return StorageRefusal(
                table.storage,
                REFUSAL_TYPE_CHANGE,
                f"{projection.column}:{column.sql_type}->{projection.sql_type}",
            )
    for column in existing.columns:
        if column.generated and column.name not in voulues:
            # La version ne la déclare plus. Sans perte : la colonne est une fonction de
            # `objet`, donc la retirer ne retire aucune donnée, et une réintroduction
            # ultérieure retrouve les mêmes valeurs.
            instructions.append(drop_column(table, column.name))
    # Les colonnes ajoutées ou retirées suffisent à dire que la base bouge ; les index
    # manquants aussi, et il faut les compter séparément — une version peut n'ajouter
    # qu'un index sur une colonne déjà là.
    colonnes_bougent = bool(instructions)
    instructions += create_indexes(table)
    voulus = {index_name(table.table, i.name) for i in table.indexes}
    voulus.add(index_name(table.table, KEY_INDEX))
    manquants = voulus - set(existing.indexes)
    retires = [nom for nom in existing.indexes if is_ours(table.table, nom) and nom not in voulus]
    instructions += [drop_index(table.schema, nom) for nom in retires]
    return instructions, colonnes_bougent or bool(manquants) or bool(retires)
