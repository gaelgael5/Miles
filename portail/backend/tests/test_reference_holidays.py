from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pytest

from miles.reference.holidays import (
    UnknownToEngineError,
    days_in_window,
    page_url,
    window,
)

# Le module des jours fériés est PUR : ces tests n'ouvrent ni base ni réseau, et le moteur
# de calendarium n'y entre que par une doublure. C'est ce qui permet d'éprouver le
# découpage de la fenêtre et le report d'un jour chômé sans charger 111 fichiers de règles.


@dataclass
class _Event:
    name: str
    free: bool = True
    observed: dt.date | None = None


@dataclass
class _Identified:
    events: list[_Event] = field(default_factory=list)


@dataclass
class _Dates:
    """Un moteur de doublure : rend ce qu'on lui a posé, année par année."""

    par_annee: dict[int, dict[dt.date, _Identified]]
    # Les années réellement demandées, pour vérifier que la fenêtre les balaie toutes.
    demandees: list[int] = field(default_factory=list)
    inconnu: bool = False

    def get_dates(self, year: int, country: str) -> dict[dt.date, Any]:
        self.demandees.append(year)
        if self.inconnu:
            # Ce que le vrai moteur rend pour un pays qu'il ne porte pas.
            raise KeyError(f"unknown country {country}")
        return dict(self.par_annee.get(year, {}))


def _un_jour(jour: dt.date, nom: str, *, free: bool = True, observed: dt.date | None = None):
    return {jour: _Identified([_Event(nom, free, observed)])}


class TestLePageUrl:
    def test_une_url_brute_devient_la_page_github(self) -> None:
        brute = (
            "https://raw.githubusercontent.com/gaelgael5/calendarium/main"
            "/src/calendarium/data/countries/date_France.json"
        )
        assert page_url(brute) == (
            "https://github.com/gaelgael5/calendarium/blob/main"
            "/src/calendarium/data/countries/date_France.json"
        )

    def test_une_url_qui_n_est_pas_brute_est_rendue_TELLE_QUELLE(self) -> None:
        # Repli volontaire : un lien qui mène quelque part vaut mieux qu'une adresse
        # dérivée de force, qui serait un 404. Le jour où le TOC est publié ailleurs,
        # l'écran garde un lien utilisable.
        autre = "https://exemple.org/regles/date_France.json"
        assert page_url(autre) == autre

    def test_une_url_brute_trop_courte_est_rendue_telle_quelle(self) -> None:
        # Pas assez de segments pour nommer un compte, un dépôt, une référence ET un
        # chemin : on ne devine pas lequel manque.
        courte = "https://raw.githubusercontent.com/gaelgael5/calendarium"
        assert page_url(courte) == courte


class TestLaFenetre:
    def test_douze_mois_vont_jusqu_au_meme_jour_l_an_prochain(self) -> None:
        assert window(dt.date(2026, 11, 11)) == (dt.date(2026, 11, 11), dt.date(2027, 11, 11))

    def test_un_29_fevrier_est_ramene_au_28(self) -> None:
        # Sans cette borne, l'écran rendrait 500 un jour tous les quatre ans — et le défaut
        # ne se reproduirait pas le lendemain, donc passerait pour un accident.
        assert window(dt.date(2028, 2, 29)) == (dt.date(2028, 2, 29), dt.date(2029, 2, 28))


class TestLesJoursDeLaFenetre:
    def test_un_jour_dans_la_fenetre_est_rendu_avec_ce_qu_il_est(self) -> None:
        dates = _Dates({2026: _un_jour(dt.date(2026, 7, 14), "Bastille Day")})
        jours = days_in_window(dates, "France", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert len(jours) == 1
        jour = jours[0]
        assert (jour.date, jour.observed, jour.name) == (
            dt.date(2026, 7, 14),
            dt.date(2026, 7, 14),
            "Bastille Day",
        )
        # `observed` est rendu MÊME quand il égale la date légale : un écran qui doit
        # tester la nullité finirait par écrire « — » là où la réponse est « le même jour ».
        assert (jour.free, jour.shifted) == (True, False)

    def test_un_jour_hors_de_la_fenetre_n_est_pas_rendu(self) -> None:
        dates = _Dates({2026: _un_jour(dt.date(2026, 1, 1), "New Year's Day")})
        assert days_in_window(dates, "France", dt.date(2026, 6, 1), dt.date(2026, 12, 31)) == []

    def test_un_jour_CHOME_dans_la_fenetre_entre_meme_si_sa_date_legale_precede(self) -> None:
        # LE cas discriminant : une fête du 31 décembre reportée au 1er janvier est chômée
        # DANS la fenêtre alors que sa date légale la précède. Ne tester que la date légale
        # l'aurait fait disparaître de l'écran — et le test serait resté vert.
        dates = _Dates(
            {2025: _un_jour(dt.date(2025, 12, 31), "New Year's Eve", observed=dt.date(2026, 1, 1))}
        )
        jours = days_in_window(dates, "France", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert [(j.date, j.observed, j.shifted) for j in jours] == [
            (dt.date(2025, 12, 31), dt.date(2026, 1, 1), True)
        ]

    def test_un_jour_LEGAL_dans_la_fenetre_entre_meme_si_son_report_la_depasse(self) -> None:
        # Le symétrique, à l'autre bout : la date légale est dedans, le report dehors.
        dates = _Dates(
            {2026: _un_jour(dt.date(2026, 12, 31), "New Year's Eve", observed=dt.date(2027, 1, 1))}
        )
        jours = days_in_window(dates, "France", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert [j.date for j in jours] == [dt.date(2026, 12, 31)]

    def test_la_fenetre_balaie_TOUTES_les_annees_qu_elle_traverse(self) -> None:
        dates = _Dates(
            {
                2026: _un_jour(dt.date(2026, 12, 25), "Christmas Day"),
                2027: _un_jour(dt.date(2027, 1, 1), "New Year's Day"),
            }
        )
        jours = days_in_window(dates, "France", dt.date(2026, 11, 11), dt.date(2027, 11, 11))

        # Les deux années traversées, PLUS une de chaque côté : un report franchit la
        # frontière d'année dans les deux sens, et les années voisines sont ce qui permet
        # de le voir. Quatre appels à 0,4 ms, contre un jour chômé manquant à l'écran.
        assert dates.demandees == [2025, 2026, 2027, 2028]
        assert [j.name for j in jours] == ["Christmas Day", "New Year's Day"]

    def test_les_jours_sont_ordonnes_sur_la_date_LEGALE(self) -> None:
        dates = _Dates(
            {
                2026: {
                    dt.date(2026, 12, 25): _Identified([_Event("Christmas Day")]),
                    dt.date(2026, 5, 1): _Identified([_Event("Labor Day")]),
                    dt.date(2026, 8, 15): _Identified([_Event("Assumption")]),
                }
            }
        )
        jours = days_in_window(dates, "France", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert [j.name for j in jours] == ["Labor Day", "Assumption", "Christmas Day"]

    def test_le_meme_jour_rendu_par_deux_annees_n_apparait_qu_une_fois(self) -> None:
        # Le moteur balaie l'année précédente et la suivante pour ses reports : la même
        # fête peut donc remonter deux fois, et l'écran la montrerait en double.
        jour = _un_jour(dt.date(2026, 12, 25), "Christmas Day")
        dates = _Dates({2026: jour, 2027: dict(jour)})
        jours = days_in_window(dates, "France", dt.date(2026, 11, 11), dt.date(2027, 11, 11))

        assert [j.name for j in jours] == ["Christmas Day"]

    def test_une_commemoration_non_chomee_est_rendue_et_marquee(self) -> None:
        # Toutes les périodes d'un fichier ne sont pas des jours de congé. Les confondre
        # ferait annoncer fermé un point relais qui ouvre.
        dates = _Dates({2026: _un_jour(dt.date(2026, 5, 8), "Victory Day", free=False)})
        jours = days_in_window(dates, "France", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert [(j.name, j.free) for j in jours] == [("Victory Day", False)]

    def test_un_pays_que_le_moteur_ne_porte_pas_est_un_refus_NOMME(self) -> None:
        # Fail closed : la base associe le pays depuis la migration 0033, le paquet
        # installé peut être une autre version. Le `KeyError` du moteur est traduit ici,
        # à la frontière de la bibliothèque.
        dates = _Dates({}, inconnu=True)
        with pytest.raises(UnknownToEngineError) as leve:
            days_in_window(dates, "Atlantis", dt.date(2026, 1, 1), dt.date(2026, 12, 31))

        assert "Atlantis" in str(leve.value)
