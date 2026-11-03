"""L'empreinte, la clé, la conformité et le compte-rendu : les calculs PURS de l'écriture.

Tout ce qui décide est ici, et rien n'y touche la base : une erreur dans ces quatre
calculs fait écrire un objet sous l'identité d'un autre, ou réécrire toute une table à
chaque import. Cela doit s'éprouver sans rien monter.

Les valeurs d'essai sont DISCRIMINANTES : un objet dont les clés sont déjà triées ne
prouverait rien du tri de la forme canonique, et une empreinte comparée à elle-même ne
prouverait rien du tout.
"""

from __future__ import annotations

import pytest

from environnement.ingestion.conformance import ModelViolation, check_conformance
from environnement.ingestion.fingerprint import canonical, fingerprint
from environnement.ingestion.keys import KeyNotExtractable, key_of
from environnement.ingestion.outcome import (
    REJECT_MODEL,
    REJECTED,
    UNCHANGED,
    WRITTEN,
    ObjectOutcome,
    Report,
    report_of,
)

MODELE = {
    "type": "object",
    "required": ["code", "libelle"],
    "properties": {
        "code": {"type": "string"},
        "libelle": {"type": "string"},
        "etat": {"type": "string", "enum": ["ouvert", "ferme"]},
        "contact": {"type": "object", "properties": {"tel": {"type": "string"}}},
    },
}


class TestEmpreinte:
    def test_l_ordre_des_cles_ne_change_pas_l_empreinte(self) -> None:
        # Discriminant : les deux dictionnaires ont les mêmes couples et un ordre
        # DIFFÉRENT, et « b » avant « a » n'est pas l'ordre trié.
        premier = {"b": 1, "a": {"z": 2, "y": 3}}
        second = {"a": {"y": 3, "z": 2}, "b": 1}

        assert fingerprint(premier) == fingerprint(second)
        assert canonical(premier) == b'{"a":{"y":3,"z":2},"b":1}'

    def test_une_valeur_qui_change_change_l_empreinte(self) -> None:
        assert fingerprint({"a": 1}) != fingerprint({"a": 2})
        # Et le TYPE compte : « 1 » n'est pas 1, et les confondre ferait manquer une
        # correction de type dans une source.
        assert fingerprint({"a": 1}) != fingerprint({"a": "1"})

    def test_l_ordre_d_un_TABLEAU_change_l_empreinte(self) -> None:
        # Le tri porte sur les clés, jamais sur les tableaux : l'ordre d'une liste est
        # une donnée, et la trier rendrait deux objets différents identiques.
        assert fingerprint({"a": [1, 2]}) != fingerprint({"a": [2, 1]})

    def test_l_empreinte_fait_32_octets(self) -> None:
        assert len(fingerprint({"a": 1})) == 32

    def test_un_accent_est_encode_en_utf8_et_non_echappe(self) -> None:
        # La forme ne dépend pas d'un réglage : « Gaël » s'encode, il ne devient pas
        # « Ga\\u00ebl ». Sans quoi l'empreinte dépendrait de l'option passée à json.
        assert canonical({"n": "Gaël"}) == '{"n":"Gaël"}'.encode()


class TestCle:
    def test_un_seul_jpath_rend_un_tableau_d_une_valeur(self) -> None:
        assert key_of({"code": "PUDO-42"}, ("$.code",)) == '["PUDO-42"]'

    def test_plusieurs_jpath_composent_dans_l_ordre_declare(self) -> None:
        objet = {"pays": "FR", "code": "42"}

        assert key_of(objet, ("$.pays", "$.code")) == '["FR","42"]'
        # L'ordre est celui de la DÉCLARATION : l'inverser désigne une autre identité.
        assert key_of(objet, ("$.code", "$.pays")) == '["42","FR"]'

    def test_une_valeur_qui_contient_le_separateur_ne_se_confond_pas(self) -> None:
        # La raison du tableau JSON plutôt que d'un séparateur : « a|b » seul et
        # (« a », « b ») doivent rester deux identités distinctes.
        assert key_of({"a": "x,y"}, ("$.a",)) != key_of({"a": "x", "b": "y"}, ("$.a", "$.b"))

    def test_un_chemin_imbrique_est_suivi(self) -> None:
        assert key_of({"contact": {"tel": "06"}}, ("$.contact.tel",)) == '["06"]'

    def test_la_cle_est_TEXTUELLE_donc_42_et_quarante_deux_designent_le_meme_objet(
        self,
    ) -> None:
        # Décision, et non effet de bord : une source qui corrige le type JSON de son
        # identifiant ne doit pas dédoubler tout le référentiel. Le test porte la
        # décision, pour que personne ne « corrige » le rendu en croyant bien faire.
        assert key_of({"n": 42}, ("$.n",)) == '["42"]'
        assert key_of({"n": 42}, ("$.n",)) == key_of({"n": "42"}, ("$.n",))

    @pytest.mark.parametrize(
        ("objet", "jpath"),
        [
            ({}, "$.code"),
            ({"code": None}, "$.code"),
            ({"contact": {}}, "$.contact.tel"),
            ({"contact": "pas-un-objet"}, "$.contact.tel"),
            ({"code": {"a": 1}}, "$.code"),
            ({"code": [1]}, "$.code"),
            ({"code": True}, "$.code"),
            ({"code": "x"}, "$.*"),
        ],
        ids=[
            "absent",
            "nul",
            "feuille-absente",
            "traverse-un-scalaire",
            "objet",
            "tableau",
            "booleen",
            "jpath-non-singulier",
        ],
    )
    def test_une_cle_qu_on_ne_peut_pas_extraire_est_un_REFUS_nomme(
        self, objet: dict[str, object], jpath: str
    ) -> None:
        # Jamais une clé vide : elle ferait écrire tous les objets fautifs les uns sur les
        # autres, sous la même identité, et aucune date ne le dirait.
        with pytest.raises(KeyNotExtractable) as refus:
            key_of(objet, (jpath,))

        assert refus.value.detail == jpath


class TestConformite:
    def test_un_objet_conforme_passe(self) -> None:
        assert check_conformance({"code": "a", "libelle": "A"}, MODELE) is None

    def test_une_propriete_obligatoire_absente_est_nommee(self) -> None:
        with pytest.raises(ModelViolation) as ecart:
            check_conformance({"code": "a"}, MODELE)

        assert "libelle" in ecart.value.detail

    def test_une_valeur_hors_enumeration_est_nommee_AVEC_son_chemin(self) -> None:
        with pytest.raises(ModelViolation) as ecart:
            check_conformance({"code": "a", "libelle": "A", "etat": "bancal"}, MODELE)

        # Le chemin, parce que c'est lui qui dit QUELLE propriété corriger dans le
        # template — « bancal n'est pas une valeur admise » ne le dit pas.
        assert ecart.value.detail.startswith("$['etat']")

    def test_le_message_est_le_MEME_a_chaque_appel(self) -> None:
        # Deux écarts dans le même objet : sans tri, `iter_errors` ne promet aucun ordre,
        # et le compte-rendu rangé en base ne serait pas reproductible.
        objet = {"etat": "bancal"}
        premier = [str(_ecart(objet)) for _ in range(5)]

        assert len(set(premier)) == 1


def _ecart(objet: dict[str, object]) -> str:
    with pytest.raises(ModelViolation) as leve:
        check_conformance(objet, MODELE)
    return leve.value.detail


class TestCompteRendu:
    def test_les_comptes_derivent_du_sort_de_chaque_objet(self) -> None:
        report = Report(received=4)
        report.objects.append(ObjectOutcome(0, WRITTEN, '["a"]'))
        report.objects.append(ObjectOutcome(1, UNCHANGED, '["b"]'))
        report.objects.append(ObjectOutcome(2, UNCHANGED, '["c"]'))
        report.objects.append(ObjectOutcome(3, REJECTED, None, REJECT_MODEL, "$['x']"))

        assert (report.written, report.unchanged, report.rejected) == (1, 2, 1)
        assert report.all_rejected is False

    def test_un_lot_entierement_rejete_se_dit(self) -> None:
        report = Report(received=1)
        report.objects.append(ObjectOutcome(0, REJECTED, None, REJECT_MODEL))

        assert report.all_rejected is True

    def test_un_lot_VIDE_n_est_pas_un_lot_rejete(self) -> None:
        # Un tableau vide est accepté par le ticket précédent (son critère 5) : zéro
        # rejet sur zéro reçu ne doit pas faire tomber l'ingestion.
        assert Report(received=0).all_rejected is False

    def test_le_compte_rendu_range_en_base_se_relit_a_l_identique(self) -> None:
        report = Report(received=2, anomalies=['cle_en_double_dans_le_lot:["a"]'])
        report.objects.append(ObjectOutcome(0, WRITTEN, '["a"]'))
        report.objects.append(ObjectOutcome(1, REJECTED, None, REJECT_MODEL, "$['x']: nope"))

        relu = report_of(report.as_json())

        assert relu.as_json() == report.as_json()
        assert relu.objects[1].detail == "$['x']: nope"
