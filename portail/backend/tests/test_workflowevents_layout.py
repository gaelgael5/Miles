"""Comment un type d'event se nomme, et ce qu'il peut désigner.

La frontière avec les modèles de données a changé de nature le 14/11/2026. Elle ne passe
plus entre deux dossiers — un type d'event n'est plus un fichier — mais entre deux rôles :
tout modèle peut servir de payload, et ce qui en fait un type d'event est qu'un
`DEFINE EVENT` le nomme. Ce que ce fichier tient, c'est donc ce que le DSL du moteur sait
ÉCRIRE : un nom de modèle ou de domaine que Miles admet et que le DSL refuse ne peut pas
entrer dans une déclaration, et le refus doit tomber à la saisie.
"""

from __future__ import annotations

import pytest

from miles.workflowevents.layout import checked_model, checked_name, checked_scope, visible
from miles.workspaces.model import WorkspaceInputError


class TestLeNommage:
    def test_le_tiret_est_refuse_parce_que_le_DSL_le_refuse(self) -> None:
        """MESURE du 11/11/2026 sur urban-workflow 0.2.1, pas une préférence.

        `DEFINE EVENT demande-soumise` rend `2:20: mismatched input '-' expecting ';'`.
        Un type d'event nommé avec un tiret serait donc inécrivable dans un script de
        workflow : le refus doit tomber à la saisie, pas au chargement du moteur.
        """
        with pytest.raises(WorkspaceInputError):
            checked_name("demande-soumise")

    @pytest.mark.parametrize("name", ["demande_soumise", "demande2", "d"])
    def test_le_souligne_et_le_chiffre_passent(self, name: str) -> None:
        assert checked_name(name) == name

    @pytest.mark.parametrize("name", ["__expired", "$_result", "Majuscule", ""])
    def test_les_noms_reserves_du_moteur_sont_hors_d_atteinte(self, name: str) -> None:
        """Aucune liste noire à tenir : la règle de nommage suffit, et on le vérifie."""
        with pytest.raises(WorkspaceInputError):
            checked_name(name)


class TestCeQueLeDslNePeutPasEcrire:
    def test_un_domaine_a_tiret_ne_peut_pas_porter_de_type_d_event(self) -> None:
        """Mesuré le 14/11/2026 : `FRAGMENT NAME mon-domaine` rend « mismatched input '-' »,
        et `AS @domains.mon-domaine.colis` de même. Le domaine reste un domaine légitime —
        il ne peut simplement pas porter de déclaration sans être renommé."""
        with pytest.raises(WorkspaceInputError) as refus:
            checked_scope("ventes-en-ligne")

        assert refus.value.field == "scope_non_ecrivable"

    def test_un_domaine_a_souligne_passe(self) -> None:
        # Discriminant : ce n'est pas « tout domaine est refusé », c'est le tiret.
        assert checked_scope("ventes_en_ligne") == "ventes_en_ligne"

    def test_un_modele_a_tiret_ne_peut_pas_etre_le_payload_d_un_type_d_event(self) -> None:
        with pytest.raises(WorkspaceInputError) as refus:
            checked_model("shared", "bon-de-commande")

        assert refus.value.field == "model_non_ecrivable"

    def test_un_modele_ecrivable_est_rendu_tel_quel(self) -> None:
        assert checked_model("achats", "commande") == ("achats", "commande")


class TestLaPortee:
    def test_un_perimetre_transverse_ne_descend_pas_dans_un_domaine(self) -> None:
        assert visible("shared", ("shared", "commande")) is True
        assert visible("shared", ("achats", "commande")) is False

    def test_un_perimetre_de_domaine_voit_son_domaine_et_les_transverses(self) -> None:
        assert visible("achats", ("achats", "commande")) is True
        assert visible("achats", ("shared", "commande")) is True
        assert visible("achats", ("ventes", "commande")) is False
