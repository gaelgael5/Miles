"""Le journal partitionné sur une base RÉELLE : c'est le seul endroit où il s'éprouve.

Aucune doublure ne peut répondre à ces questions — une partition manquante, une purge qui
retire une journée entière, la monotonie d'un compteur qui survit à l'effacement sont des
comportements de PostgreSQL, pas de notre code. Enabler `8e86afbc`.

L'horloge est INJECTÉE partout : un test qui attendrait minuit ne serait pas un test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from miles_socle.events.catalog import EventCatalog, EventShape, introduced_by
from miles_socle.events.categories import of_number
from miles_socle.events.history import db_object_history
from miles_socle.events.journal import JOURNAL_TABLES, db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.journal.maintenance import JournalMaintenance
from miles_socle.journal.partitions import partition_name
from miles_socle.journal.store import db_partition_days, db_partitioned

from .environnement_stack import open_stack


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

TYPE = "environment.identity_created"
AUTEUR = EventAuthor("local", "admin")
OBJET = ObjectRef("essai", "o1")
TROIS_NOVEMBRE = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def _catalogue() -> EventCatalog:
    return _catalogue_de(TYPE)


async def _ecrire(pool: asyncpg.Pool, quand: datetime, objet: ObjectRef = OBJET) -> None:
    """Écrit un event à cet instant, par le MÊME chemin que la production."""
    async with pool.acquire() as cnx, cnx.transaction():
        await db_write_event(cnx, NewEvent(TYPE, (objet,), AUTEUR), _catalogue(), lambda: quand)


def _entretien(
    pool: asyncpg.Pool, quand: datetime, retention: int | None = None
) -> JournalMaintenance:
    return JournalMaintenance(
        pool=pool, tables=JOURNAL_TABLES, now=lambda: quand, retention_days=retention
    )


async def _jours(pool: asyncpg.Pool, table: str) -> set[date]:
    async with pool.acquire() as cnx:
        return await db_partition_days(cnx, table)


class TestLaFormeDuJournal:
    async def test_les_deux_tables_du_journal_sont_partitionnees(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack, stack.pool.acquire() as cnx:
            for table in JOURNAL_TABLES:
                assert await db_partitioned(cnx, table) is True
            # Le compteur de séquences, lui, NE l'est pas : c'est de l'état, pas du
            # journal, et le purger ferait repartir les numéros.
            assert await db_partitioned(cnx, "event_object_sequences") is False

    async def test_un_event_atterrit_dans_la_partition_de_SA_journee(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, TROIS_NOVEMBRE)

            async with stack.pool.acquire() as cnx:
                rangement = await cnx.fetch(
                    "SELECT tableoid::regclass::text AS partition FROM events"
                )
                liens = await cnx.fetch(
                    "SELECT tableoid::regclass::text AS partition FROM event_objects"
                )

            assert [r["partition"] for r in rangement] == [
                partition_name("events", date(2026, 11, 3))
            ]
            assert [r["partition"] for r in liens] == [
                partition_name("event_objects", date(2026, 11, 3))
            ]

    async def test_les_frontieres_de_journee_sont_en_UTC(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Constaté, pas supposé (critère 8). 23 h 30 le 3 et 00 h 30 le 4 : deux journées."""
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, datetime(2026, 11, 3, 23, 30, tzinfo=UTC))
            await _ecrire(stack.pool, datetime(2026, 11, 4, 0, 30, tzinfo=UTC))

            async with stack.pool.acquire() as cnx:
                rows = await cnx.fetch(
                    "SELECT tableoid::regclass::text AS partition, count(*) AS n"
                    " FROM events GROUP BY 1 ORDER BY 1"
                )

            assert [(r["partition"], r["n"]) for r in rows] == [
                (partition_name("events", date(2026, 11, 3)), 1),
                (partition_name("events", date(2026, 11, 4)), 1),
            ]


class TestLAvance:
    async def test_l_entretien_pose_aujourd_hui_et_sept_jours_d_avance(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Comparé à ce qui était DÉJÀ là, et non à `changed`.

        La migration pose elle-même sept jours d'avance, à partir de `current_date` — la
        vraie date du jour. Affirmer que l'entretien a posé quelque chose ferait donc
        dépendre ce test du calendrier : vert le 3 novembre 2026, rouge le lendemain. Ce
        qui est invariant, c'est que les huit journées soient là APRÈS, et que l'entretien
        ait posé exactement celles qui manquaient.
        """
        async with open_stack(blank_db, tmp_path) as stack:
            deja = {table: await _jours(stack.pool, table) for table in JOURNAL_TABLES}

            rapport = await _entretien(stack.pool, TROIS_NOVEMBRE).resolve_maintain()

            attendues = {date(2026, 11, 3) + timedelta(days=n) for n in range(8)}
            for compte_rendu in rapport.tables:
                jours = await _jours(stack.pool, compte_rendu.table)
                assert attendues <= jours
                assert date(2026, 11, 11) not in attendues
                assert set(compte_rendu.created) == attendues - deja[compte_rendu.table]

    async def test_rejouer_l_entretien_ne_pose_rien_et_ne_tombe_pas_en_erreur(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Critère 6. `changed` est FAUX au second passage : tout le SQL est idempotent,
        donc le succès ne dirait rien de l'effet."""
        async with open_stack(blank_db, tmp_path) as stack:
            entretien = _entretien(stack.pool, TROIS_NOVEMBRE)
            await entretien.resolve_maintain()

            second = await entretien.resolve_maintain()

            assert second.changed is False
            assert all(not t.created and not t.dropped for t in second.tables)

    async def test_une_ecriture_dont_la_partition_MANQUE_la_pose_et_reussit(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """La réparation à l'écriture. Mesuré : sans elle, PostgreSQL REFUSE l'insertion
        (`23514, no partition of relation … found for row`) et la modification que l'event
        trace serait perdue avec lui."""
        async with open_stack(blank_db, tmp_path) as stack:
            # Très loin devant l'avance posée par la migration : aucune partition pour ce
            # jour-là, donc l'écriture n'a d'autre choix que de la créer.
            lointain = TROIS_NOVEMBRE + timedelta(days=400)
            assert lointain.date() not in await _jours(stack.pool, "events")

            await _ecrire(stack.pool, lointain)

            assert lointain.date() in await _jours(stack.pool, "events")
            assert lointain.date() in await _jours(stack.pool, "event_objects")
            async with stack.pool.acquire() as cnx:
                assert await cnx.fetchval("SELECT count(*) FROM events") == 1
                assert await cnx.fetchval("SELECT count(*) FROM event_objects") == 1

    async def test_la_reparation_ne_perd_pas_la_modification_que_l_event_trace(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Le point de sauvegarde. Sans lui, l'insertion refusée avorterait la transaction
        de la modification elle-même, et c'est la modification qui serait perdue."""
        lointain = TROIS_NOVEMBRE + timedelta(days=400)
        async with open_stack(blank_db, tmp_path) as stack:
            async with stack.pool.acquire() as cnx, cnx.transaction():
                await cnx.execute("CREATE TABLE modification_temoin (marque text)")
                await cnx.execute("INSERT INTO modification_temoin VALUES ('posee')")
                await db_write_event(
                    cnx,
                    NewEvent(TYPE, (OBJET,), AUTEUR),
                    _catalogue(),
                    lambda: lointain,
                )

            async with stack.pool.acquire() as cnx:
                assert await cnx.fetchval("SELECT marque FROM modification_temoin") == "posee"
                assert await cnx.fetchval("SELECT count(*) FROM events") == 1


class TestLaPurge:
    async def test_une_retention_de_trois_jours_laisse_exactement_les_trois_derniers(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            for recul in range(6):
                await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=recul))

            await _entretien(stack.pool, TROIS_NOVEMBRE, retention=3).resolve_maintain()

            async with stack.pool.acquire() as cnx:
                restants = await cnx.fetch(
                    "SELECT (written_at AT TIME ZONE 'UTC')::date AS jour FROM events ORDER BY jour"
                )
            assert [r["jour"] for r in restants] == [
                date(2026, 11, 1),
                date(2026, 11, 2),
                date(2026, 11, 3),
            ]

    async def test_la_purge_retire_des_PARTITIONS_et_non_des_lignes(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """L'interdit du ticket : purger ligne à ligne est précisément ce que le
        partitionnement sert à ne pas faire."""
        async with open_stack(blank_db, tmp_path) as stack:
            vieux = TROIS_NOVEMBRE - timedelta(days=5)
            await _ecrire(stack.pool, vieux)

            rapport = await _entretien(stack.pool, TROIS_NOVEMBRE, retention=2).resolve_maintain()

            assert [vieux.date()] == [j for t in rapport.tables for j in t.dropped][:1]
            assert vieux.date() not in await _jours(stack.pool, "events")
            async with stack.pool.acquire() as cnx:
                existe = await cnx.fetchval(
                    "SELECT count(*) FROM pg_class WHERE relname = $1",
                    partition_name("events", vieux.date()),
                )
            assert existe == 0

    async def test_sans_retention_rien_n_est_purge(self, blank_db: str, tmp_path: Path) -> None:
        """Critère 5. Un paramètre oublié laisse grossir ; il n'efface pas."""
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=400))

            rapport = await _entretien(
                stack.pool, TROIS_NOVEMBRE, retention=None
            ).resolve_maintain()

            assert all(not t.dropped for t in rapport.tables)
            async with stack.pool.acquire() as cnx:
                assert await cnx.fetchval("SELECT count(*) FROM events") == 1

    async def test_rejouer_la_purge_ne_retire_rien_de_plus(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=5))
            entretien = _entretien(stack.pool, TROIS_NOVEMBRE, retention=2)
            await entretien.resolve_maintain()

            second = await entretien.resolve_maintain()

            assert all(not t.dropped for t in second.tables)

    async def test_une_purge_ne_laisse_AUCUN_lien_orphelin(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Critère 10, et la raison d'être de la recopie de `written_at`.

        La clé étrangère a dû être retirée pour que la purge soit possible (PostgreSQL
        refuse de retirer une partition dont une contrainte dépend). Ce qui la remplace,
        c'est que les deux partitions du même jour tombent dans la même transaction — et
        c'est cela qu'on éprouve ici, puisque plus rien dans la base ne l'impose.
        """
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=5))
            await _ecrire(stack.pool, TROIS_NOVEMBRE)

            await _entretien(stack.pool, TROIS_NOVEMBRE, retention=2).resolve_maintain()

            async with stack.pool.acquire() as cnx:
                orphelins = await cnx.fetchval(
                    "SELECT count(*) FROM event_objects o"
                    " WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id = o.event_id)"
                )
                liens = await cnx.fetchval("SELECT count(*) FROM event_objects")
            assert orphelins == 0
            assert liens == 1

    async def test_le_compteur_de_sequences_SURVIT_et_la_suite_continue(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Critère 11. Si le compteur était purgé, le numéro repartirait à 1 et deux events
        du même objet porteraient le même rang — l'histoire deviendrait illisible, et
        `missing_sequences` ne pourrait plus rien signaler."""
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=5))
            await _ecrire(stack.pool, TROIS_NOVEMBRE - timedelta(days=4))

            await _entretien(stack.pool, TROIS_NOVEMBRE, retention=1).resolve_maintain()
            await _ecrire(stack.pool, TROIS_NOVEMBRE)

            async with stack.pool.acquire() as cnx:
                assert (
                    await cnx.fetchval(
                        "SELECT last_sequence FROM event_object_sequences"
                        " WHERE object_kind = $1 AND object_id = $2",
                        OBJET.kind,
                        OBJET.id,
                    )
                    == 3
                )
                histoire = await db_object_history(cnx, OBJET)
            # Le troisième event reste seul, et les deux premiers numéros sont SIGNALÉS
            # absents : une histoire incomplète se dit, elle ne se devine pas.
            assert [e.sequences[OBJET] for e in histoire.events] == [3]
            assert histoire.missing_sequences == [1, 2]


class TestLaRouteDEntretien:
    async def test_le_declencheur_exterieur_entretient_avec_son_jeton(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            stack.app.state.journal_maintenance = _entretien(stack.pool, TROIS_NOVEMBRE)
            stack.app.state.journal_maintenance_token = "jeton-de-la-stack"

            reponse = await stack.anonymous().post(
                MAINTENANCE_PATH, headers={"Authorization": "Bearer jeton-de-la-stack"}
            )

            assert reponse.status_code == 200
            assert reponse.json()["day"] == "2026-11-03"
            assert date(2026, 11, 10) in await _jours(stack.pool, "events")

    async def test_sans_jeton_la_route_refuse_et_n_entretient_rien(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            stack.app.state.journal_maintenance = _entretien(stack.pool, TROIS_NOVEMBRE)
            stack.app.state.journal_maintenance_token = "jeton-de-la-stack"
            avant = await _jours(stack.pool, "events")

            reponse = await stack.anonymous().post(MAINTENANCE_PATH)

            assert reponse.status_code == 401
            assert await _jours(stack.pool, "events") == avant
