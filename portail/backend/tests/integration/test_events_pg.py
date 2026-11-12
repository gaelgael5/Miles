from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.events.catalog import EventCatalog, EventShape, introduced_by
from miles_socle.events.categories import of_number
from miles_socle.events.history import db_object_history
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef
from miles_socle.events.search import EventFilter
from miles_socle.events.service import EventsService
from miles_socle.events.store_search import FoundEvent

from miles.config import DEFAULT_MIGRATIONS_DIR


def _catalogue_de(*noms: str) -> EventCatalog:
    """Un catalogue de test pour ces types, bloc OUVERT.

    Ouvert parce que ces tests éprouvent le JOURNAL — écriture, partitions, séquences — et
    non la validation du bloc, qui a son propre fichier. Un bloc fermé les ferait rougir
    pour une raison sans rapport avec ce qu'ils vérifient.
    """
    return EventCatalog(
        introduced_by(
            of_number(0),
            tuple(EventShape(nom, nom, {"type": "object"}) for nom in noms),
        )
    )


pytestmark = pytest.mark.integration

CATALOG = _catalogue_de("thing.created", "thing.updated")
AUTHOR = EventAuthor("local", "admin")
# Table d'essai : une « modification » quelconque, que l'event doit accompagner.
THINGS = "CREATE TABLE things (id text PRIMARY KEY, label text NOT NULL)"


def _now() -> datetime:
    return datetime.now(UTC)


def _event(*ids: str, kind: str = "thing.created") -> NewEvent:
    return NewEvent(kind, tuple(ObjectRef("thing", i) for i in ids), AUTHOR, {"n": len(ids)})


@pytest.fixture
async def db(blank_db: str) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(blank_db, min_size=2, max_size=4)
    async with pool.acquire() as conn:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        await conn.execute(THINGS)
    try:
        yield pool
    finally:
        await pool.close()


async def _count(pool: asyncpg.Pool, table: str) -> int:
    value: int = await pool.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608  # nom fixe
    return value


async def test_failure_after_writes_leaves_neither_object_nor_event(db: asyncpg.Pool) -> None:
    async with db.acquire() as conn:
        with pytest.raises(RuntimeError, match="panne"):
            async with conn.transaction():
                await conn.execute("INSERT INTO things VALUES ('t1', 'a')")
                await db_write_event(conn, _event("t1"), CATALOG, _now)
                raise RuntimeError("panne avant commit")

    assert await _count(db, "things") == 0
    assert await _count(db, "events") == 0
    assert await _count(db, "event_object_sequences") == 0


async def test_event_write_failure_fails_the_modification(db: asyncpg.Pool) -> None:
    async with db.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute("INSERT INTO things VALUES ('t1', 'a')")
                await conn.execute(
                    "ALTER TABLE events ADD CONSTRAINT refuse_tout CHECK (type = 'jamais')"
                )
                await db_write_event(conn, _event("t1"), CATALOG, _now)

    assert await _count(db, "things") == 0


async def test_sequences_are_consecutive_per_object_and_multi_object_event(
    db: asyncpg.Pool,
) -> None:
    async with db.acquire() as conn:
        for _ in range(3):
            async with conn.transaction():
                await db_write_event(conn, _event("a"), CATALOG, _now)
        async with conn.transaction():
            written = await db_write_event(conn, _event("a", "b"), CATALOG, _now)

        history_a = await db_object_history(conn, ObjectRef("thing", "a"))
        history_b = await db_object_history(conn, ObjectRef("thing", "b"))

    assert written.sequences == {ObjectRef("thing", "a"): 4, ObjectRef("thing", "b"): 1}
    assert len(history_a.events) == 4 and history_a.missing_sequences == []
    assert history_b.events[0].id == written.id
    assert await _count(db, "events") == 4


async def test_concurrent_events_on_same_object_get_distinct_consecutive_numbers(
    db: asyncpg.Pool,
) -> None:
    async def write_one() -> int:
        async with db.acquire() as conn, conn.transaction():
            written = await db_write_event(conn, _event("same"), CATALOG, _now)
            return written.sequences[ObjectRef("thing", "same")]

    numbers = await asyncio.gather(*(write_one() for _ in range(20)))

    assert sorted(numbers) == list(range(1, 21))


async def test_events_on_different_objects_do_not_wait_for_each_other(db: asyncpg.Pool) -> None:
    async with db.acquire() as holder:
        transaction = holder.transaction()
        await transaction.start()
        try:
            # Le verrou sur « a » reste tenu pendant l'écriture sur « b ».
            await db_write_event(holder, _event("a"), CATALOG, _now)
            async with db.acquire() as other, other.transaction():
                await asyncio.wait_for(db_write_event(other, _event("b"), CATALOG, _now), 2)
        finally:
            await transaction.rollback()


async def test_overlapping_mass_events_do_not_deadlock(db: asyncpg.Pool) -> None:
    ids = [f"o{i}" for i in range(50)]

    async def write(order: list[str]) -> None:
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(conn, _event(*order), CATALOG, _now)

    await asyncio.wait_for(asyncio.gather(write(ids), write(list(reversed(ids)))), 10)

    async with db.acquire() as conn:
        history = await db_object_history(conn, ObjectRef("thing", "o0"))
    assert len(history.events) == 2


async def test_missing_sequence_is_detected_on_read(db: asyncpg.Pool) -> None:
    async with db.acquire() as conn:
        for _ in range(3):
            async with conn.transaction():
                await db_write_event(conn, _event("g"), CATALOG, _now)
        await conn.execute("DELETE FROM event_objects WHERE object_id = 'g' AND sequence = 2")

        history = await db_object_history(conn, ObjectRef("thing", "g"))

    assert history.missing_sequences == [2]


async def _median_cost(db: asyncpg.Pool, count: int, with_event: bool, rounds: int) -> float:
    durations = []
    for round_number in range(rounds):
        ids = [f"{count}-{with_event}-{round_number}-{i}" for i in range(count)]
        async with db.acquire() as conn:
            started = time.perf_counter()
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO things SELECT id, 'x' FROM unnest($1::text[]) AS t(id)", ids
                )
                if with_event:
                    await db_write_event(conn, _event(*ids), CATALOG, _now)
            durations.append(time.perf_counter() - started)
    # Médiane : un seul tirage lent ne doit décider ni dans un sens ni dans l'autre.
    return sorted(durations)[rounds // 2]


async def test_event_overhead_on_mass_modification_is_proportional_to_objects(
    db: asyncpg.Pool,
) -> None:
    # Critère 11, reformulé par Gael le 19/10/2026 : pas de seuil x2 (numéroter chaque
    # objet écrit au moins une ligne indexée par objet), mais un surcoût proportionnel
    # au nombre d'objets, mesuré et suivi. Le suivi est la ligne imprimée ci-dessous.
    small, large, rounds = 500, 2000, 5
    overhead = {}
    for count in (small, large):
        baseline = await _median_cost(db, count, with_event=False, rounds=rounds)
        traced = await _median_cost(db, count, with_event=True, rounds=rounds)
        overhead[count] = traced - baseline
        print(
            f"surcoût de l'event, {count} objets : {overhead[count] * 1000:.1f} ms"
            f" ({overhead[count] / count * 1e6:.1f} µs/objet, x{traced / baseline:.2f})"
        )

    # Linéaire : 4 fois plus d'objets, environ 4 fois plus de surcoût. Une croissance
    # quadratique donnerait 16 ; la marge absorbe le bruit d'une machine partagée.
    growth = overhead[large] / overhead[small]
    assert growth < (large / small) * 1.5


class TestLaRacineCommuneDesEvents:
    """Les trois champs que la racine apporte, sur une base réelle (12/11/2026).

    La doublure du socle dit qu'ils partent en paramètre ; seule une base dit qu'ils
    atterrissent, qu'ils se relisent par le chemin de l'écran, et que la garde de base
    refuse ce que l'application refuse déjà.
    """

    AILLEURS = datetime(2026, 11, 10, 7, 30, tzinfo=UTC)

    async def _page(self, pool: asyncpg.Pool) -> tuple[FoundEvent, ...]:
        return (await EventsService(pool, _now).resolve_search(EventFilter(), 1, 50)).page.events

    async def test_les_trois_champs_font_l_aller_retour_par_le_chemin_de_l_ecran(
        self, db: asyncpg.Pool
    ) -> None:
        event = NewEvent(
            "thing.created",
            (ObjectRef("thing", "t1"),),
            AUTHOR,
            {"n": 1},
            external_id="msg-4242",
            dedup_key="t1:2026-11-10",
            creation_date=self.AILLEURS,
        )
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, CATALOG, _now)

        relu = (await self._page(db))[0]

        assert (relu.external_id, relu.dedup_key, relu.creation_date) == (
            "msg-4242",
            "t1:2026-11-10",
            self.AILLEURS,
        )
        # Le bloc de propriétés ne les a pas absorbés : ils sont en colonnes.
        assert relu.properties == {"n": 1}

    async def test_un_event_sans_ces_champs_se_relit_sans_tomber(self, db: asyncpg.Pool) -> None:
        """Le cas des events écrits AVANT le 12/11/2026 : trois colonnes nulles."""
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(conn, _event("t1"), CATALOG, _now)

        relu = (await self._page(db))[0]

        assert (relu.external_id, relu.dedup_key, relu.creation_date) == (None, None, None)

    async def test_la_base_refuse_une_chaine_vide_que_l_application_refuse_deja(
        self, db: asyncpg.Pool
    ) -> None:
        """Garde de dernier recours : un `UPDATE` direct ne doit pas pouvoir la poser.

        L'application refuse la chaîne vide dans `NewEvent` ; ce test éprouve l'AUTRE
        barrière, celle qui tiendra le jour où un correctif écrira en SQL.
        """
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(conn, _event("t1"), CATALOG, _now)

        with pytest.raises(asyncpg.CheckViolationError, match="events_external_id_non_vide"):
            await db.execute("UPDATE events SET external_id = ''")


@pytest.mark.integration
class TestLaCategorieDesEvents:
    """La colonne posée le 12/11/2026, sur une base réelle.

    La doublure dit que le numéro part en paramètre ; seule une base dit qu'il atterrit
    dans une colonne `NOT NULL`, qu'il se relit par le chemin de l'écran, et que la garde
    de base refuse ce que le code refuse.
    """

    async def _page(self, pool: asyncpg.Pool) -> tuple[FoundEvent, ...]:
        return (await EventsService(pool, _now).resolve_search(EventFilter(), 1, 50)).page.events

    async def test_la_categorie_du_type_fait_l_aller_retour(self, db: asyncpg.Pool) -> None:
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(
                conn,
                NewEvent("thing.created", (ObjectRef("thing", "t1"),), AUTHOR, {}),
                CATALOG,
                _now,
            )

        relu = (await self._page(db))[0]

        # Zéro parce que `CATALOG` déclare ses types sous `backoffice-configuration`, qui
        # est la catégorie de ce produit — et c'est le catalogue qui l'a posée, pas l'event.
        assert relu.category == 0

    async def test_la_base_refuse_un_numero_negatif(self, db: asyncpg.Pool) -> None:
        """La seule borne que la base tient : les numéros sont des rangs. La borne HAUTE
        est au code, qui nomme la catégorie inconnue — l'énumération n'est pas close, et un
        CHECK à sept valeurs aurait demandé une migration par catégorie ajoutée."""
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(
                conn,
                NewEvent("thing.created", (ObjectRef("thing", "t2"),), AUTHOR, {}),
                CATALOG,
                _now,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("UPDATE events SET category = -1")

    async def test_la_colonne_n_admet_pas_le_nul(self, db: asyncpg.Pool) -> None:
        """Ce qui distingue cette colonne des trois autres champs de la racine : elles sont
        nullables parce qu'un geste de l'atelier n'en a aucun, alors qu'un event a TOUJOURS
        une catégorie — son type la déclare. Un nul laisserait l'IHM de configuration sans
        son verrou de lecture seule."""
        async with db.acquire() as conn, conn.transaction():
            await db_write_event(
                conn,
                NewEvent("thing.created", (ObjectRef("thing", "t3"),), AUTHOR, {}),
                CATALOG,
                _now,
            )
        with pytest.raises(asyncpg.NotNullViolationError):
            await db.execute("UPDATE events SET category = NULL")
