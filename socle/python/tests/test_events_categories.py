from __future__ import annotations

import pytest

from miles_socle.events.categories import (
    CATEGORIES,
    UnknownCategoryError,
    of_number,
    of_slug,
)


class TestLesCategoriesDEvent:
    """Qui introduit l'event, et donc qui peut l'éditer (Gael, 12/11/2026)."""

    def test_les_numeros_et_les_noms_sont_uniques(self) -> None:
        # Un doublon de numéro ferait pointer deux catégories sur la même valeur stockée,
        # et la relecture en choisirait une au hasard du dictionnaire.
        assert len({item.number for item in CATEGORIES}) == len(CATEGORIES)
        assert len({item.slug for item in CATEGORIES}) == len(CATEGORIES)

    def test_les_numeros_sont_ceux_qui_ont_ete_poses(self) -> None:
        """Ils sont STABLES : réordonner la liste changerait la valeur d'events déjà
        écrits, donc ce test est là pour que personne ne la réordonne par confort."""
        assert [(item.number, item.slug) for item in CATEGORIES] == [
            (0, "backoffice-configuration"),
            (1, "backoffice-enrolement"),
            (2, "backoffice-environnement"),
            (3, "system-front"),
            (4, "device-socle"),
            (5, "device-fonctionnel"),
        ]

    def test_une_seule_categorie_est_editable_dans_l_ihm(self) -> None:
        """Le verrou de l'écran se LIT de la catégorie : « si l'event est introduit par du
        code, dans ce cas il est en lecture seule dans l'ihm »."""
        editables = [item.slug for item in CATEGORIES if not item.code_introduced]

        assert editables == ["device-fonctionnel"]

    def test_une_categorie_se_retrouve_par_son_nom_et_par_son_numero(self) -> None:
        assert of_slug("device-fonctionnel") is of_number(5)

    @pytest.mark.parametrize(
        ("appel", "valeur", "attendu"),
        [
            (of_slug, "system-backend", "system-backend"),
            (of_slug, "", "''"),
            (of_number, 6, "6"),
            (of_number, -1, "-1"),
        ],
        ids=["nom-regroupe-abandonne", "nom-vide", "numero-hors-liste", "numero-negatif"],
    )
    def test_un_inconnu_est_refuse_en_le_nommant(self, appel, valeur, attendu: str) -> None:
        """Aucun repli : une catégorie inconnue ne devient pas la première de la liste.
        `system-backend` est discriminant — c'était le regroupement abandonné le
        12/11/2026, donc exactement la valeur qu'un appelant mal à jour enverrait."""
        with pytest.raises(UnknownCategoryError, match=attendu):
            appel(valeur)
