"""La consultation du journal sur une base RÉELLE : les index, la fenêtre, les filtres.

Les index se vérifient dans le catalogue de PostgreSQL et non dans le texte de la
migration : ce qui compte est qu'une partition créée APRÈS coup les porte aussi, et seule
la base le dit. Story `50bfcba0`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from miles_socle.events.api_events import EVENTS_PATH
from miles_socle.events.journal import JOURNAL_TABLES, db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.events.search import EventFilter
from miles_socle.events.service import EventsService
from miles_socle.journal.maintenance import JournalMaintenance
from miles_socle.journal.partitions import partition_name

from .environnement_stack import open_stack

pytestmark = pytest.mark.integration

PREMIER = "environment.identity_created"
SECOND = "environment.storages_materialised"
CATALOGUE = EventTypeCatalog(frozenset({PREMIER, SECOND}))
ADMIN = EventAuthor("local", "admin")
CLE = EventAuthor("apikey", "k-123")
STORAGE = ObjectRef("storage", "sites")
MAINTENANT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

INDEX_ATTENDUS = (
    "events_written_at_idx",
    "events_type_written_at_idx",
    "events_author_written_at_idx",
    "events_functional_at_idx",
)


async def _ecrire(
    pool: asyncpg.Pool,
    quand: datetime,
    *,
    type_: str = PREMIER,
    auteur: EventAuthor = ADMIN,
    objet: ObjectRef = STORAGE,
    fonctionnelle: datetime | None = None,
) -> None:
    async with pool.acquire() as cnx, cnx.transaction():
        await db_write_event(
            cnx,
            NewEvent(type_, (objet,), auteur, functional_at=fonctionnelle),
            CATALOGUE,
            lambda: quand,
        )


def _service(pool: asyncpg.Pool, quand: datetime = MAINTENANT) -> EventsService:
    return EventsService(pool=pool, now=lambda: quand)


class TestLesIndex:
    async def test_les_index_du_minimum_sont_poses_sur_la_table_partitionnee(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack, stack.pool.acquire() as cnx:
            noms = {
                row["indexrelid"]
                for row in await cnx.fetch(
                    "SELECT indexrelid::regclass::text AS indexrelid FROM pg_index"
                    " WHERE indrelid = 'events'::regclass"
                )
            }

        assert set(INDEX_ATTENDUS) <= noms

    async def test_une_partition_creee_APRES_porte_les_memes_index(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """C'est ce qui rend ces index compatibles avec une rétention glissante : la
        partition que l'entretien posera demain les reçoit sans que personne y pense.
        Mesuré le 03/11/2026, et éprouvé ici sur le dispositif réel."""
        lointain = MAINTENANT + timedelta(days=500)
        async with open_stack(blank_db, tmp_path) as stack:
            entretien = JournalMaintenance(
                pool=stack.pool, tables=JOURNAL_TABLES, now=lambda: lointain, days_ahead=0
            )
            await entretien.resolve_maintain()

            nom = partition_name("events", lointain.date())
            async with stack.pool.acquire() as cnx:
                # Par l'HÉRITAGE et non par les noms : PostgreSQL nomme l'index d'une
                # partition d'après ses COLONNES, donc
                # `events_author_written_at_idx` devient
                # `events_<jour>_author_directory_author_subject_written_at_idx`. Comparer
                # des noms ferait rougir ce test pour une raison sans rapport — c'est ce
                # qui s'est produit le 03/11/2026. `pg_inherits` relie chaque index de
                # partition à l'index du parent dont il descend : c'est exactement la
                # question posée.
                herites = {
                    row["parent"]
                    for row in await cnx.fetch(
                        "SELECT parent.relname AS parent"
                        " FROM pg_inherits i"
                        " JOIN pg_class parent ON parent.oid = i.inhparent"
                        " JOIN pg_class enfant ON enfant.oid = i.inhrelid"
                        " WHERE enfant.relkind = 'i' AND enfant.relname LIKE $1",
                        f"{nom}%",
                    )
                }

            assert set(INDEX_ATTENDUS) <= herites, sorted(herites)


class TestLaFenetre:
    async def test_sans_borne_la_reponse_DIT_la_fenetre_qu_elle_a_appliquee(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            resultat = await _service(stack.pool).resolve_search(EventFilter(), 1, 50)

        assert resultat.window.defaulted is True
        assert resultat.window.start == MAINTENANT - timedelta(days=7)

    async def test_un_event_HORS_de_la_fenetre_par_defaut_n_est_pas_rendu(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """Et c'est bien pour cela que la fenêtre doit se dire : sinon l'écran montre
        sept jours en laissant croire qu'il montre tout."""
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT - timedelta(days=30))
            await _ecrire(stack.pool, MAINTENANT - timedelta(days=1))

            dedans = await _service(stack.pool).resolve_search(EventFilter(), 1, 50)
            tout = await _service(stack.pool).resolve_search(
                EventFilter(written_from=MAINTENANT - timedelta(days=60)), 1, 50
            )

        assert dedans.page.total == 1
        assert tout.page.total == 2
        assert tout.window.defaulted is False


class TestLesFiltres:
    async def test_le_type_filtre_et_un_type_inconnu_rend_une_page_VIDE(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT, type_=PREMIER)
            await _ecrire(stack.pool, MAINTENANT, type_=SECOND)

            trouve = await _service(stack.pool).resolve_search(EventFilter(type=SECOND), 1, 50)
            inconnu = await _service(stack.pool).resolve_search(
                EventFilter(type="rien.du.tout"), 1, 50
            )

        assert [e.type for e in trouve.page.events] == [SECOND]
        # Une page vide, pas une erreur : un type qui n'existe pas encore est un cas
        # ordinaire, pas une faute de l'appelant.
        assert inconnu.page.total == 0
        assert inconnu.page.events == ()

    async def test_l_auteur_filtre_sur_l_identite_entiere_donc_aussi_par_cle_d_API(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT, auteur=ADMIN)
            await _ecrire(stack.pool, MAINTENANT, auteur=CLE)

            par_cle = await _service(stack.pool).resolve_search(
                EventFilter(author_directory="apikey", author_subject="k-123"), 1, 50
            )

        assert [e.author_subject for e in par_cle.page.events] == ["k-123"]

    async def test_l_objet_rend_son_histoire_dans_l_ordre_des_sequences(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        autre = ObjectRef("storage", "comptes")
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT - timedelta(hours=3), objet=STORAGE)
            await _ecrire(stack.pool, MAINTENANT - timedelta(hours=2), objet=autre)
            await _ecrire(stack.pool, MAINTENANT - timedelta(hours=1), objet=STORAGE)

            histoire = await _service(stack.pool).resolve_search(
                EventFilter(object_kind="storage", object_id="sites"), 1, 50
            )

        rangs = [o.sequence for e in histoire.page.events for o in e.objects]
        # Le plus récent d'abord : la séquence 2, puis la 1.
        assert rangs == [2, 1]
        assert histoire.missing_sequences == ()

    async def test_les_DEUX_dates_se_filtrent_separement(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        """L'event est ÉCRIT aujourd'hui et porte une date métier d'il y a trente jours —
        une confirmation tardive. Sans deux filtres distincts, les deux seraient
        indiscernables et l'un des deux ne servirait à rien."""
        tardif = MAINTENANT - timedelta(days=30)
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT, fonctionnelle=tardif)

            par_ecriture = await _service(stack.pool).resolve_search(EventFilter(), 1, 50)
            par_metier = await _service(stack.pool).resolve_search(
                EventFilter(functional_to=MAINTENANT - timedelta(days=20)), 1, 50
            )
            hors_metier = await _service(stack.pool).resolve_search(
                EventFilter(functional_from=MAINTENANT - timedelta(days=1)), 1, 50
            )

        assert par_ecriture.page.total == 1
        assert par_metier.page.total == 1
        assert hors_metier.page.total == 0

    async def test_un_type_qui_ressemble_a_du_SQL_ne_casse_rien(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, MAINTENANT)

            trouve = await _service(stack.pool).resolve_search(
                EventFilter(type="x'; DROP TABLE events; --"), 1, 50
            )

            assert trouve.page.total == 0
            async with stack.pool.acquire() as cnx:
                assert await cnx.fetchval("SELECT count(*) FROM events") == 1


class TestLaPagination:
    async def test_deux_pages_ne_se_recouvrent_pas_et_n_omettent_rien(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            for n in range(5):
                await _ecrire(stack.pool, MAINTENANT - timedelta(minutes=n))

            service = _service(stack.pool)
            premiere = await service.resolve_search(EventFilter(), 1, 2)
            seconde = await service.resolve_search(EventFilter(), 2, 2)
            troisieme = await service.resolve_search(EventFilter(), 3, 2)

        identifiants = [e.id for e in premiere.page.events + seconde.page.events]
        assert len(set(identifiants)) == 4
        assert premiere.page.total == 5
        assert len(troisieme.page.events) == 1


class TestLaRoute:
    async def test_la_route_exige_une_session(self, blank_db: str, tmp_path: Path) -> None:
        """Le journal dit qui a fait quoi : l'ouvrir rendrait publique l'activité des
        administrateurs de l'instance."""
        async with open_stack(blank_db, tmp_path) as stack:
            reponse = await stack.anonymous().get(EVENTS_PATH)

        assert reponse.status_code == 401

    async def test_une_session_lit_le_journal_et_la_reponse_porte_sa_fenetre(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            await _ecrire(stack.pool, datetime.now(UTC))

            reponse = await stack.client.get(EVENTS_PATH)

            assert reponse.status_code == 200
            corps: dict[str, Any] = reponse.json()
            assert corps["total"] == 1
            assert corps["window"]["defaulted"] is True
            assert corps["events"][0]["type"] == PREMIER
            assert corps["events"][0]["objects"] == [
                {"kind": "storage", "id": "sites", "sequence": 1}
            ]

    async def test_des_bornes_inversees_sont_refusees_et_NOMMEES(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            reponse = await stack.client.get(
                EVENTS_PATH,
                params={
                    "written_from": "2026-11-03T00:00:00Z",
                    "written_to": "2026-11-01T00:00:00Z",
                },
            )

        assert reponse.status_code == 400
        assert reponse.json()["detail"]["code"] == "bornes_inversees"

    async def test_une_moitie_d_auteur_est_refusee_et_non_appliquee_a_moitie(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            reponse = await stack.client.get(EVENTS_PATH, params={"author_directory": "local"})

        assert reponse.status_code == 400
        assert reponse.json()["detail"]["code"] == "auteur_incomplet"

    async def test_une_taille_de_page_non_bornee_est_refusee(
        self, blank_db: str, tmp_path: Path
    ) -> None:
        async with open_stack(blank_db, tmp_path) as stack:
            reponse = await stack.client.get(EVENTS_PATH, params={"size": "100000"})

        assert reponse.status_code == 400
        assert reponse.json()["detail"]["code"] == "page_invalide"


async def test_lire_le_journal_n_ECRIT_aucun_event(blank_db: str, tmp_path: Path) -> None:
    """Un event « journal consulté » le ferait grossir de sa propre lecture."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _ecrire(stack.pool, datetime.now(UTC))

        await stack.client.get(EVENTS_PATH)
        await stack.client.get(EVENTS_PATH)

        async with stack.pool.acquire() as cnx:
            assert await cnx.fetchval("SELECT count(*) FROM events") == 1


async def test_la_journee_d_un_event_est_celle_de_son_ECRITURE(
    blank_db: str, tmp_path: Path
) -> None:
    """`written_at` et non `functional_at` comme clé de partition : une date métier
    antérieure rangerait l'event dans une journée déjà purgée."""
    async with open_stack(blank_db, tmp_path) as stack:
        quand = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        await _ecrire(stack.pool, quand, fonctionnelle=datetime(2026, 1, 15, tzinfo=UTC))

        async with stack.pool.acquire() as cnx:
            rangement = await cnx.fetchval("SELECT tableoid::regclass::text FROM events LIMIT 1")

    assert rangement == partition_name("events", date(2026, 11, 3))
