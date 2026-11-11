"""Modifier UNE propriété d'un schéma : ce que la mutation garde, et ce qu'elle refuse.

Ce que ces tests tiennent surtout : **ce que l'appel ne nomme pas ne bouge pas**. C'est la
raison d'être de la primitive (Gael, 11/11/2026 : « ça permettra aux IA de générer de plus
petits artefacts ») ; une mutation qui perdrait un `$defs` ou un mot-clef d'extension en
chemin rendrait l'artefact petit et la modification dangereuse.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from miles.datamodels.patch import PropertyPathError, patched, remove_property, set_property

COLIS: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "miles:/shared/colis",
    "title": "Colis",
    "type": "object",
    "required": ["reference"],
    "properties": {
        "reference": {"type": "string", "format": "uuid"},
        "destinataire": {"$ref": "miles:/shared/personne"},
        "adresse": {"type": "object", "properties": {"ville": {"type": "string"}}},
        "lignes": {
            "type": "array",
            "items": {"type": "object", "properties": {"article": {"type": "string"}}},
        },
        # Mot-clef d'extension : porte l'utilité des champs depuis le 05/11/2026.
        "poids": {"type": "number", "x-miles": {"usage": "etiquette"}},
    },
    "$defs": {"tarif": {"type": "number"}},
}


def _codes(document: dict[str, Any], path: list[str], schema: Any = None) -> tuple[str, list[str]]:
    with pytest.raises(PropertyPathError) as refused:
        if schema is None:
            remove_property(document, path)
        else:
            set_property(document, path, schema)
    return refused.value.code, refused.value.existing


class TestPoserUnePropriete:
    def test_une_propriete_neuve_s_ajoute_sans_toucher_au_reste(self) -> None:
        patche = set_property(COLIS, ["etat"], {"type": "string"})

        assert patche["properties"]["etat"] == {"type": "string"}
        # Tout le reste, à l'identique — y compris `$defs` et `x-miles`, que personne
        # n'aurait pensé à renvoyer dans un remplacement entier écrit à la main.
        assert patche["$defs"] == {"tarif": {"type": "number"}}
        assert patche["properties"]["poids"]["x-miles"] == {"usage": "etiquette"}
        assert patche["required"] == ["reference"]
        assert patche["$id"] == "miles:/shared/colis"

    def test_le_document_d_origine_n_est_pas_modifie(self) -> None:
        # Discriminant : une mutation en place ferait passer ce test par accident si on
        # comparait le patch à lui-même.
        set_property(COLIS, ["etat"], {"type": "string"})

        assert "etat" not in COLIS["properties"]

    def test_une_propriete_existante_est_remplacee(self) -> None:
        patche = set_property(COLIS, ["reference"], {"type": "integer"})

        assert patche["properties"]["reference"] == {"type": "integer"}
        assert list(patche["properties"]) == list(COLIS["properties"])

    def test_un_renvoi_s_ajoute_comme_n_importe_quelle_propriete(self) -> None:
        """Il n'y a pas de primitive à part pour les renvois : c'est une propriété."""
        patche = set_property(COLIS, ["expediteur"], {"$ref": "miles:/shared/personne"})

        assert patche["properties"]["expediteur"] == {"$ref": "miles:/shared/personne"}

    def test_un_renvoi_existant_se_change(self) -> None:
        patche = set_property(COLIS, ["destinataire"], {"$ref": "miles:/shared/societe"})

        assert patche["properties"]["destinataire"] == {"$ref": "miles:/shared/societe"}

    def test_une_propriete_imbriquee_se_pose_dans_son_objet(self) -> None:
        patche = set_property(COLIS, ["adresse", "code_postal"], {"type": "string"})

        assert set(patche["properties"]["adresse"]["properties"]) == {"ville", "code_postal"}
        assert patche["properties"]["adresse"]["type"] == "object"

    def test_une_propriete_des_elements_d_un_tableau_se_pose_par_le_segment_vide(self) -> None:
        patche = set_property(COLIS, ["lignes", "[]", "quantite"], {"type": "integer"})

        items = patche["properties"]["lignes"]["items"]
        assert set(items["properties"]) == {"article", "quantite"}

    def test_un_objet_sans_properties_en_recoit_une(self) -> None:
        # Le cas d'un schéma tout juste déclaré : `{type: object, properties: {}}`, ou
        # même sans la clef du tout.
        patche = set_property({"type": "object"}, ["nom"], {"type": "string"})

        assert patche == {"type": "object", "properties": {"nom": {"type": "string"}}}


class TestLObligation:
    def test_required_vrai_ajoute_la_propriete_aux_obligatoires(self) -> None:
        patche = set_property(COLIS, ["etat"], {"type": "string"}, required=True)

        assert patche["required"] == ["reference", "etat"]

    def test_required_faux_la_retire(self) -> None:
        patche = set_property(COLIS, ["reference"], {"type": "string"}, required=False)

        assert "required" not in patche

    def test_required_omis_ne_touche_pas_a_la_liste(self) -> None:
        """Corriger un type ne doit pas dégrader une obligation qu'on n'a pas nommée."""
        patche = set_property(COLIS, ["reference"], {"type": "integer"})

        assert patche["required"] == ["reference"]

    def test_required_vrai_deux_fois_ne_double_pas_le_nom(self) -> None:
        patche = set_property(COLIS, ["reference"], {"type": "string"}, required=True)

        assert patche["required"] == ["reference"]


class TestRetirerUnePropriete:
    def test_la_propriete_et_son_obligation_partent_ensemble(self) -> None:
        """La laisser dans `required` ferait un schéma qu'aucun document ne satisfait."""
        patche = remove_property(COLIS, ["reference"])

        assert "reference" not in patche["properties"]
        assert "required" not in patche

    def test_le_reste_du_schema_est_conserve(self) -> None:
        patche = remove_property(COLIS, ["poids"])

        assert set(patche["properties"]) == {"reference", "destinataire", "adresse", "lignes"}
        assert patche["$defs"] == {"tarif": {"type": "number"}}

    def test_une_propriete_imbriquee_se_retire(self) -> None:
        patche = remove_property(COLIS, ["adresse", "ville"])

        assert patche["properties"]["adresse"]["properties"] == {}

    def test_une_propriete_absente_est_refusee_en_NOMMANT_ce_qui_existe(self) -> None:
        code, existants = _codes(COLIS, ["etat"])

        assert code == "propriete_inconnue"
        assert "reference" in existants and "poids" in existants


class TestLesRefusDeChemin:
    def test_un_renvoi_ne_se_traverse_pas(self) -> None:
        """Le schéma désigné vit dans un AUTRE document : y écrire par ce chemin
        modifierait un fichier que l'appel ne nomme pas. Le refus nomme la cible."""
        code, existants = _codes(COLIS, ["destinataire", "nom"], {"type": "string"})

        assert code == "renvoi_traverse"
        assert existants == ["miles:/shared/personne"]

    def test_un_scalaire_ne_porte_pas_de_propriete(self) -> None:
        code, _ = _codes(COLIS, ["reference", "trop", "loin"], {"type": "string"})

        assert code == "propriete_inconnue"

    def test_le_segment_de_tableau_exige_des_items(self) -> None:
        code, _ = _codes(COLIS, ["adresse", "[]", "ville"], {"type": "string"})

        assert code == "tableau_sans_items"

    def test_un_chemin_vide_est_refuse(self) -> None:
        code, _ = _codes(COLIS, [], {"type": "string"})

        assert code == "chemin_vide"

    def test_le_segment_de_tableau_ne_nomme_pas_une_propriete(self) -> None:
        code, _ = _codes(COLIS, ["lignes", "[]"], {"type": "string"})

        assert code == "nom_de_propriete_attendu"


class TestLaReecriture:
    def test_le_document_repart_en_yaml_avec_ses_accents(self) -> None:
        texte = patched(
            yaml.safe_dump(COLIS, allow_unicode=True, sort_keys=False),
            lambda d: set_property(d, ["etat"], {"title": "État", "type": "string"}),
        )

        assert "État" in texte
        assert yaml.safe_load(texte)["properties"]["etat"]["type"] == "string"

    def test_un_document_qui_n_est_pas_un_objet_est_refuse(self) -> None:
        with pytest.raises(PropertyPathError) as refused:
            patched("- une\n- liste\n", lambda d: d)

        assert refused.value.code == "document_non_objet"
