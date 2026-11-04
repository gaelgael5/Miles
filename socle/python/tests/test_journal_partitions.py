from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from miles_socle.journal.partitions import (
    create_partition,
    days_to_ensure,
    drop_partition,
    expired_days,
    partition_day,
    partition_name,
)

TROIS_NOVEMBRE = date(2026, 11, 3)


class TestLeNomDUnePartition:
    def test_le_nom_porte_la_journee(self) -> None:
        assert partition_name("events", TROIS_NOVEMBRE) == "events_20261103"

    def test_le_jour_se_relit_depuis_le_nom(self) -> None:
        assert partition_day("events", "events_20261103") == TROIS_NOVEMBRE

    def test_une_partition_d_une_AUTRE_table_n_est_pas_reconnue(self) -> None:
        """`event_objects_20261103` commence par `events`… mais n'en est pas une partition."""
        assert partition_day("event", "events_20261103") is None

    @pytest.mark.parametrize(
        "nom",
        [
            "events_a_la_main",
            "events_2026110",
            "events_202611030",
            "events_20261332",
            "events",
            "autre_20261103",
        ],
    )
    def test_ce_qui_n_est_PAS_de_nous_n_est_jamais_rendu(self, nom: str) -> None:
        """Rendre un jour pour une partition qu'on n'a pas posée la ferait purger."""
        assert partition_day("events", nom) is None


class TestLeSqlDesPartitions:
    def test_la_creation_borne_la_journee_et_tolere_le_deja_la(self) -> None:
        sql = create_partition("events", TROIS_NOVEMBRE)

        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert '"events_20261103" PARTITION OF "events"' in sql
        # Le fuseau est EXPLICITE : les frontières de journée ne doivent pas dépendre du
        # fuseau de la session qui joue la requête.
        assert "FROM ('2026-11-03 00:00:00+00:00') TO ('2026-11-04 00:00:00+00:00')" in sql

    def test_la_suppression_tolere_l_absente_pour_etre_rejouable(self) -> None:
        assert drop_partition("events", TROIS_NOVEMBRE) == (
            'DROP TABLE IF EXISTS "events_20261103"'
        )


class TestLesJoursAPoser:
    def test_aujourd_hui_et_les_sept_suivants(self) -> None:
        jours = days_to_ensure(TROIS_NOVEMBRE)

        assert jours[0] == TROIS_NOVEMBRE
        assert jours[-1] == date(2026, 11, 10)
        assert len(jours) == 8

    def test_sans_avance_il_reste_aujourd_hui(self) -> None:
        assert days_to_ensure(TROIS_NOVEMBRE, ahead=0) == [TROIS_NOVEMBRE]

    def test_une_avance_negative_est_refusee(self) -> None:
        with pytest.raises(ValueError, match="ahead"):
            days_to_ensure(TROIS_NOVEMBRE, ahead=-1)


PRESENTES = frozenset(
    {
        date(2026, 10, 30),
        date(2026, 10, 31),
        date(2026, 11, 1),
        date(2026, 11, 2),
        TROIS_NOVEMBRE,
        # À venir : posée d'avance par l'entretien.
        date(2026, 11, 4),
    }
)


class TestCeQuiAExpire:
    def test_une_retention_absente_ne_retire_RIEN(self) -> None:
        """Un paramètre oublié laisse grossir ; il n'efface pas."""
        assert expired_days(set(PRESENTES), TROIS_NOVEMBRE, None) == []

    def test_une_retention_de_trois_jours_laisse_exactement_les_trois_derniers(self) -> None:
        expires = expired_days(set(PRESENTES), TROIS_NOVEMBRE, 3)

        # Gardés : le 1er, le 2 et le 3 novembre. Le 4 est à venir, il n'expire pas.
        assert expires == [date(2026, 10, 30), date(2026, 10, 31)]

    def test_une_retention_d_un_jour_ne_laisse_qu_aujourd_hui(self) -> None:
        expires = expired_days(set(PRESENTES), TROIS_NOVEMBRE, 1)

        assert date(2026, 11, 2) in expires
        assert TROIS_NOVEMBRE not in expires
        assert date(2026, 11, 4) not in expires

    def test_les_partitions_A_VENIR_ne_sont_jamais_retirees(self) -> None:
        """Sinon chaque passage défairait l'avance que le passage vient de poser."""
        assert date(2026, 11, 4) not in expired_days(set(PRESENTES), TROIS_NOVEMBRE, 1)

    def test_une_retention_de_zero_jour_est_refusee(self) -> None:
        """« Zéro » ne veut pas dire « ne rien purger » : ça, c'est l'absence de valeur."""
        with pytest.raises(ValueError, match="au moins 1 jour"):
            expired_days(set(PRESENTES), TROIS_NOVEMBRE, 0)

    def test_rien_en_base_ne_fait_rien_expirer(self) -> None:
        assert expired_days(set(), TROIS_NOVEMBRE, 1) == []


def test_la_journee_se_calcule_sur_l_instant_UTC() -> None:
    """Les bornes sont en UTC : la base l'est (`0001_socle.sql`), et on le constate.

    23 h 30 à Paris le 3 novembre, c'est 22 h 30 UTC — donc encore le 3. Une heure plus
    tard, c'est le 4 : la frontière est celle d'UTC, pas celle du lecteur.
    """
    veille = datetime(2026, 11, 3, 23, 30, tzinfo=UTC)
    apres = datetime(2026, 11, 4, 0, 30, tzinfo=UTC)

    assert veille.date() == TROIS_NOVEMBRE
    assert apres.date() == date(2026, 11, 4)
