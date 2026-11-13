"""Où se rangent les événements de workflow, et comment ils se nomment.

La frontière avec les modèles de données est le sujet de ce fichier : c'est elle que le
choix de la « liste séparée » (Gael, 11/11/2026) demande de tenir, et elle ne tient que
si un chemin, un nom et un `$id` d'événement ne sont jamais pris pour ceux d'un modèle.
"""

from __future__ import annotations

import pytest

from miles.datamodels.layout import entry_of as model_entry_of
from miles.datamodels.schema import target_of
from miles.workflowevents.layout import (
    EventEntry,
    checked_name,
    checked_scope,
    entry_of,
    event_id,
    event_path,
    visible,
)
from miles.workspaces.model import WorkspaceInputError


class TestLesChemins:
    @pytest.mark.parametrize(
        ("scope", "name", "path"),
        [
            ("shared", "demande_soumise", "shared/events/demande_soumise.yaml"),
            ("achats", "validation", "domains/achats/events/validation.yaml"),
        ],
    )
    def test_un_evenement_se_range_sous_events_et_se_relit_de_son_chemin(
        self, scope: str, name: str, path: str
    ) -> None:
        assert event_path(scope, name) == path
        assert entry_of(path) == EventEntry(scope, name, path)

    def test_les_metadonnees_ne_sont_pas_prises_pour_un_evenement(self) -> None:
        # Le point est hors de la règle de nommage : `<nom>.meta.yaml` ne peut pas être lu
        # comme un événement nommé « demande_soumise.meta ».
        assert entry_of("shared/events/demande_soumise.meta.yaml") is None

    def test_un_modele_n_est_pas_un_evenement_et_reciproquement(self) -> None:
        """La frontière, dans les deux sens : c'est tout l'objet de la liste séparée."""
        assert entry_of("shared/models/commande.yaml") is None
        assert model_entry_of("shared/events/demande_soumise.yaml") is None


class TestLeNommage:
    def test_le_tiret_est_refuse_parce_que_le_DSL_le_refuse(self) -> None:
        """MESURE du 11/11/2026 sur urban-workflow 0.2.1, pas une préférence.

        `DEFINE EVENT demande-soumise` rend `2:20: mismatched input '-' expecting ';'`.
        Un événement nommé avec un tiret serait donc inécrivable dans un script de
        workflow : le refus doit tomber à la saisie, pas au chargement du moteur.
        """
        with pytest.raises(WorkspaceInputError):
            checked_name("demande-soumise")

    @pytest.mark.parametrize("name", ["demande_soumise", "demande2", "d"])
    def test_le_souligne_et_le_chiffre_passent(self, name: str) -> None:
        assert checked_name(name) == name

    def test_le_tiret_reste_admis_dans_un_nom_de_DOMAINE(self) -> None:
        # Discriminant : c'est le nom de l'ÉVÉNEMENT que le DSL contraint, pas celui du
        # domaine, qui ne devient qu'un nom de dossier.
        assert checked_scope("ventes-en-ligne") == "ventes-en-ligne"

    @pytest.mark.parametrize("name", ["__expired", "$_result", "Majuscule", ""])
    def test_les_noms_reserves_du_moteur_sont_hors_d_atteinte(self, name: str) -> None:
        """Aucune liste noire à tenir : la règle de nommage suffit, et on le vérifie."""
        with pytest.raises(WorkspaceInputError):
            checked_name(name)


class TestLIdentifiant:
    @pytest.mark.parametrize(
        ("scope", "name", "identifier"),
        [
            ("shared", "demande_soumise", "miles:/events/shared/demande_soumise"),
            ("achats", "validation", "miles:/events/domains/achats/validation"),
        ],
    )
    def test_l_id_porte_le_segment_events(self, scope: str, name: str, identifier: str) -> None:
        assert event_id(scope, name) == identifier

    @pytest.mark.parametrize(
        ("scope", "name"), [("shared", "demande_soumise"), ("achats", "validation")]
    )
    def test_aucun_storage_ni_source_ne_peut_designer_un_evenement(
        self, scope: str, name: str
    ) -> None:
        """C'est CE test qui tient la frontière voulue par la liste séparée.

        `target_of` est la fonction par laquelle un storage, une source ou un modèle
        résolvent un `miles:/…`. Si elle rendait un couple pour l'`$id` d'un événement,
        un storage pourrait projeter un événement comme s'il était un modèle.
        """
        assert target_of(event_id(scope, name)) is None


class TestLaPortee:
    def test_un_evenement_transverse_ne_descend_pas_dans_un_domaine(self) -> None:
        transverse = EventEntry("shared", "ping", event_path("shared", "ping"))
        assert visible(transverse, ("shared", "commande")) is True
        assert visible(transverse, ("achats", "commande")) is False

    def test_un_evenement_de_domaine_voit_son_domaine_et_les_transverses(self) -> None:
        local = EventEntry("achats", "ping", event_path("achats", "ping"))
        assert visible(local, ("achats", "commande")) is True
        assert visible(local, ("shared", "commande")) is True
        assert visible(local, ("ventes", "commande")) is False
