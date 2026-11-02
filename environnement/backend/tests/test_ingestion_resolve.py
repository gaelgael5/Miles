from __future__ import annotations

import json

import pytest
from miles_socle.parametrage.sources import MAX_BATCH, Entry, EntryModes, SourceDoc

from environnement.ingestion.model import (
    BATCH,
    ELEMENT,
    FILE,
    MAX_BODY_BYTES,
    REFUSAL_CORPS_TROP_GRAND,
    REFUSAL_CORPS_VIDE,
    REFUSAL_JSON_INVALIDE,
    REFUSAL_LOT_TROP_GRAND,
    REFUSAL_MODE_AMBIGU,
    REFUSAL_MODE_INCONNU,
    REFUSAL_MODE_NON_DECLARE,
    REFUSAL_MODE_NON_SERVI,
    REFUSAL_OBJET_ATTENDU,
    REFUSAL_SOURCE_ILLISIBLE,
    REFUSAL_SOURCE_INCONNUE,
    REFUSAL_TABLEAU_ATTENDU,
    IngestionRefusal,
)
from environnement.ingestion.resolve import objects_of, target_of
from environnement.sources.declarations import DeclaredSources


def _entree(
    *, element: bool = False, tableau: bool = False, fichier: bool = False, modele: str = "d/m"
) -> Entry:
    return Entry(
        kind="web",
        source_model=modele,
        chain="c",
        modes=EntryModes(element=element, batch=tableau, file=fichier),
        split="",
        unified_transaction=False,
        write_batch=100,
    )


def _declarees(
    *entrees: Entry, nom: str = "comptes", illisibles: tuple[str, ...] = ()
) -> DeclaredSources:
    return DeclaredSources(
        {nom: SourceDoc(nom, nom.title(), "accounts", entrees)} if entrees else {},
        illisibles,
    )


class TestCeQuUneAdresseDesigne:
    def test_le_mode_choisit_l_entree_et_rend_son_modele(self) -> None:
        declarees = _declarees(_entree(element=True, modele="pudo/compte"))

        cible = target_of(declarees, "comptes", ELEMENT)

        assert (cible.source, cible.mode) == ("comptes", ELEMENT)
        assert cible.entry.source_model == "pudo/compte"

    def test_un_mode_qui_n_existe_pas_est_refuse_avant_tout(self) -> None:
        with pytest.raises(IngestionRefusal) as refus:
            target_of(_declarees(_entree(element=True)), "comptes", "massif")

        assert refus.value.code == REFUSAL_MODE_INCONNU

    def test_une_source_non_declaree_est_refusee(self) -> None:
        with pytest.raises(IngestionRefusal) as refus:
            target_of(_declarees(_entree(element=True)), "inventee", ELEMENT)

        assert (refus.value.code, refus.value.detail) == (REFUSAL_SOURCE_INCONNUE, "inventee")

    def test_une_source_declaree_mais_illisible_est_distincte_d_une_absente(self) -> None:
        """On ne devine pas ce qu'une déclaration fautive voulait exposer — et le geste à
        faire n'est pas le même : là il faut déclarer, ici il faut corriger."""
        with pytest.raises(IngestionRefusal) as refus:
            target_of(_declarees(illisibles=("cassee",)), "cassee", ELEMENT)

        assert refus.value.code == REFUSAL_SOURCE_ILLISIBLE

    def test_un_mode_que_l_entree_ne_coche_pas_est_refuse(self) -> None:
        with pytest.raises(IngestionRefusal) as refus:
            target_of(_declarees(_entree(element=True)), "comptes", BATCH)

        assert (refus.value.code, refus.value.detail) == (REFUSAL_MODE_NON_DECLARE, BATCH)

    def test_deux_entrees_exposant_le_meme_mode_font_REFUSER_et_non_choisir(self) -> None:
        """Deviner enverrait le lot dans la mauvaise chaîne, sans que rien ne le signale."""
        declarees = _declarees(
            _entree(element=True, modele="pudo/compte"),
            _entree(element=True, modele="pudo/partenaire"),
        )

        with pytest.raises(IngestionRefusal) as refus:
            target_of(declarees, "comptes", ELEMENT)

        assert refus.value.code == REFUSAL_MODE_AMBIGU

    def test_deux_entrees_de_modes_differents_ne_sont_pas_ambigues(self) -> None:
        declarees = _declarees(
            _entree(element=True, modele="pudo/compte"),
            _entree(tableau=True, modele="pudo/partenaire"),
        )

        assert target_of(declarees, "comptes", ELEMENT).entry.source_model == "pudo/compte"
        assert target_of(declarees, "comptes", BATCH).entry.source_model == "pudo/partenaire"

    def test_le_mode_fichier_declare_est_refuse_comme_NON_SERVI(self) -> None:
        """Distinct de « non déclaré » : le geste à faire n'est pas de cocher le mode,
        c'est d'attendre la story qui le sert. Accepter sans effet laisserait croire
        qu'un lot a été pris en charge."""
        with pytest.raises(IngestionRefusal) as refus:
            target_of(_declarees(_entree(fichier=True)), "comptes", FILE)

        assert (refus.value.code, refus.value.detail) == (REFUSAL_MODE_NON_SERVI, FILE)


class TestLeCorpsRecu:
    def test_un_objet_seul_en_mode_element(self) -> None:
        assert objects_of(ELEMENT, b'{"Id": "A-1"}') == [{"Id": "A-1"}]

    def test_un_tableau_en_mode_tableau(self) -> None:
        assert objects_of(BATCH, b'[{"Id": "A-1"}, {"Id": "A-2"}]') == [
            {"Id": "A-1"},
            {"Id": "A-2"},
        ]

    def test_un_tableau_VIDE_est_accepte_et_vaut_zero_objet(self) -> None:
        """À distinguer d'un corps vide : un export légitimement vide n'est pas une
        erreur d'appel, et le confondre ferait croire à un client qu'il a déposé."""
        assert objects_of(BATCH, b"[]") == []

    def test_un_corps_vide_est_une_erreur_d_appel(self) -> None:
        for corps in (b"", b"   ", b"\n"):
            with pytest.raises(IngestionRefusal) as refus:
                objects_of(BATCH, corps)
            assert refus.value.code == REFUSAL_CORPS_VIDE

    def test_un_json_invalide_dit_OU_il_pêche(self) -> None:
        """Sans la position, l'appelant doit chercher dans un document qu'il n'a pas
        sous les yeux."""
        with pytest.raises(IngestionRefusal) as refus:
            objects_of(BATCH, b'[{"Id": "A-1",}]')

        assert refus.value.code == REFUSAL_JSON_INVALIDE
        assert refus.value.detail is not None
        assert "ligne" in refus.value.detail and "colonne" in refus.value.detail

    def test_un_tableau_sur_le_mode_element_est_refuse_et_l_inverse_aussi(self) -> None:
        with pytest.raises(IngestionRefusal) as refus:
            objects_of(ELEMENT, b"[{}]")
        assert refus.value.code == REFUSAL_OBJET_ATTENDU

        with pytest.raises(IngestionRefusal) as autre:
            objects_of(BATCH, b"{}")
        assert autre.value.code == REFUSAL_TABLEAU_ATTENDU

    def test_un_item_qui_n_est_pas_un_objet_est_refuse_en_disant_son_rang(self) -> None:
        with pytest.raises(IngestionRefusal) as refus:
            objects_of(BATCH, b'[{"Id": "A-1"}, "A-2"]')

        assert (refus.value.code, refus.value.detail) == (REFUSAL_OBJET_ATTENDU, "[1]")

    def test_un_scalaire_seul_est_refuse_dans_les_deux_modes(self) -> None:
        for mode, code in ((ELEMENT, REFUSAL_OBJET_ATTENDU), (BATCH, REFUSAL_TABLEAU_ATTENDU)):
            with pytest.raises(IngestionRefusal) as refus:
                objects_of(mode, b"42")
            assert refus.value.code == code

    def test_le_plafond_du_mode_tableau_est_dit_quand_il_est_depasse(self) -> None:
        """Sans le plafond, l'appelant ne sait pas s'il doit couper en deux ou en vingt."""
        juste = json.dumps([{"i": n} for n in range(MAX_BATCH)]).encode()
        trop = json.dumps([{"i": n} for n in range(MAX_BATCH + 1)]).encode()

        assert len(objects_of(BATCH, juste)) == MAX_BATCH
        with pytest.raises(IngestionRefusal) as refus:
            objects_of(BATCH, trop)
        assert (refus.value.code, refus.value.detail) == (REFUSAL_LOT_TROP_GRAND, str(MAX_BATCH))

    def test_un_corps_trop_grand_est_refuse_SANS_etre_analyse(self) -> None:
        """La borne en octets existe parce que le compte d'objets ne se connaît qu'après
        avoir tout lu : sans elle, un corps énorme serait chargé avant d'être refusé."""
        with pytest.raises(IngestionRefusal) as refus:
            objects_of(BATCH, b"x" * (MAX_BODY_BYTES + 1))

        assert (refus.value.code, refus.value.detail) == (
            REFUSAL_CORPS_TROP_GRAND,
            str(MAX_BODY_BYTES),
        )
