from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from miles_socle.events.search import (
    DEFAULT_WINDOW,
    MAX_PAGE_SIZE,
    REFUSAL_AUTHOR,
    REFUSAL_OBJECT,
    REFUSAL_PAGE,
    REFUSAL_WINDOW,
    EventFilter,
    SearchRefusal,
    Window,
    checked_page,
    conditions,
    missing_in_range,
    resolve_window,
)

MAINTENANT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
FENETRE = Window(MAINTENANT - DEFAULT_WINDOW, MAINTENANT, True)


class TestLaFenetre:
    def test_sans_borne_la_fenetre_est_recente_et_se_DIT_par_defaut(self) -> None:
        """Un écran qui montre sept jours en laissant croire qu'il montre tout est pire
        qu'un écran vide : la réponse doit porter le fait."""
        fenetre = resolve_window(EventFilter(), MAINTENANT)

        assert fenetre.start == MAINTENANT - timedelta(days=7)
        assert fenetre.end == MAINTENANT
        assert fenetre.defaulted is True

    def test_une_borne_donnee_n_est_plus_un_defaut(self) -> None:
        depuis = datetime(2026, 10, 1, tzinfo=UTC)

        fenetre = resolve_window(EventFilter(written_from=depuis), MAINTENANT)

        assert fenetre.start == depuis
        assert fenetre.end == MAINTENANT
        assert fenetre.defaulted is False

    def test_des_bornes_inversees_sont_refusees_et_nommees(self) -> None:
        filtre = EventFilter(written_from=MAINTENANT, written_to=MAINTENANT - timedelta(days=1))

        with pytest.raises(SearchRefusal) as refus:
            resolve_window(filtre, MAINTENANT)

        assert refus.value.code == REFUSAL_WINDOW
        assert "written_at" in refus.value.detail

    def test_des_bornes_FONCTIONNELLES_inversees_sont_refusees_a_part(self) -> None:
        """Deux filtres distincts, donc deux refus distincts : confondre les deux ferait
        parler d'une date d'écriture pour une date métier."""
        filtre = EventFilter(
            functional_from=MAINTENANT, functional_to=MAINTENANT - timedelta(days=1)
        )

        with pytest.raises(SearchRefusal) as refus:
            resolve_window(filtre, MAINTENANT)

        assert "functional_at" in refus.value.detail


class TestLaPage:
    def test_la_premiere_page_est_la_une(self) -> None:
        assert checked_page(1, 50) == (1, 50)

    @pytest.mark.parametrize("page", [0, -1])
    def test_une_page_avant_la_premiere_est_refusee(self, page: int) -> None:
        with pytest.raises(SearchRefusal) as refus:
            checked_page(page, 50)

        assert refus.value.code == REFUSAL_PAGE

    @pytest.mark.parametrize("taille", [0, -1, MAX_PAGE_SIZE + 1])
    def test_une_taille_non_bornee_est_refusee(self, taille: int) -> None:
        """Sans borne, un appelant demande tout le journal en une page."""
        with pytest.raises(SearchRefusal):
            checked_page(1, taille)

    def test_la_taille_maximale_elle_meme_passe(self) -> None:
        assert checked_page(1, MAX_PAGE_SIZE) == (1, MAX_PAGE_SIZE)


class TestLesConditions:
    def test_la_borne_d_ecriture_est_TOUJOURS_la_et_en_premier(self) -> None:
        """C'est la clé de partition : sans elle, la requête considère tout le journal."""
        ou, valeurs = conditions(EventFilter(), FENETRE)

        assert ou == "e.written_at >= $1 AND e.written_at < $2"
        assert valeurs == [FENETRE.start, FENETRE.end]

    def test_le_type_s_ajoute_en_parametre_jamais_en_texte(self) -> None:
        ou, valeurs = conditions(EventFilter(type="secret.created"), FENETRE)

        assert ou.endswith("AND e.type = $3")
        assert valeurs[2] == "secret.created"

    def test_un_type_qui_ressemble_a_du_SQL_reste_une_VALEUR(self) -> None:
        mechant = "x'; DROP TABLE events; --"

        ou, valeurs = conditions(EventFilter(type=mechant), FENETRE)

        assert "DROP" not in ou
        assert valeurs[2] == mechant

    def test_l_auteur_exige_ses_DEUX_moities(self) -> None:
        with pytest.raises(SearchRefusal) as refus:
            conditions(EventFilter(author_directory="local"), FENETRE)

        assert refus.value.code == REFUSAL_AUTHOR

    def test_un_auteur_complet_filtre_sur_l_identite_entiere(self) -> None:
        ou, valeurs = conditions(
            EventFilter(author_directory="apikey", author_subject="k1"), FENETRE
        )

        assert "e.author_directory = $3 AND e.author_subject = $4" in ou
        assert valeurs[2:] == ["apikey", "k1"]

    def test_l_objet_exige_ses_DEUX_moities(self) -> None:
        with pytest.raises(SearchRefusal) as refus:
            conditions(EventFilter(object_id="s1"), FENETRE)

        assert refus.value.code == REFUSAL_OBJECT

    def test_l_objet_joint_sur_la_cle_de_partition_aussi(self) -> None:
        """Sans `written_at` dans la jointure, la lecture parcourt toutes les partitions
        des liens — le partitionnement n'aurait servi qu'à la moitié de la requête."""
        ou, _ = conditions(EventFilter(object_kind="storage", object_id="s1"), FENETRE)

        assert "o.written_at = e.written_at" in ou

    def test_les_deux_dates_se_filtrent_SEPAREMENT(self) -> None:
        filtre = EventFilter(
            written_from=MAINTENANT - timedelta(days=1),
            functional_from=MAINTENANT - timedelta(days=30),
        )

        ou, valeurs = conditions(filtre, resolve_window(filtre, MAINTENANT))

        assert "e.functional_at >= $3" in ou
        assert valeurs[0] == MAINTENANT - timedelta(days=1)
        assert valeurs[2] == MAINTENANT - timedelta(days=30)

    def test_tous_les_filtres_ensemble_numerotent_leurs_parametres_sans_trou(self) -> None:
        filtre = EventFilter(
            type="t",
            author_directory="local",
            author_subject="admin",
            object_kind="k",
            object_id="i",
            functional_from=MAINTENANT,
            functional_to=MAINTENANT,
        )

        ou, valeurs = conditions(filtre, FENETRE)

        rangs = [int(m) for m in re.findall(r"\$(\d+)", ou)]
        assert rangs == list(range(1, len(valeurs) + 1))


class TestLesSequencesManquantes:
    def test_une_suite_complete_ne_signale_rien(self) -> None:
        assert missing_in_range([1, 2, 3]) == []

    def test_un_trou_A_L_INTERIEUR_est_signale(self) -> None:
        assert missing_in_range([3, 6, 4]) == [5]

    def test_le_numero_1_absent_n_est_PAS_un_trou(self) -> None:
        """Et c'est la différence avec `db_object_history` : ici la recherche est bornée
        dans le temps, et la purge de rétention efface les premiers events par
        construction. Réclamer le 1 signalerait un trou à chaque fois."""
        assert missing_in_range([7, 8, 9]) == []

    def test_un_seul_event_ne_permet_de_conclure_a_rien(self) -> None:
        assert missing_in_range([42]) == []

    def test_aucun_event_ne_signale_rien(self) -> None:
        assert missing_in_range([]) == []
