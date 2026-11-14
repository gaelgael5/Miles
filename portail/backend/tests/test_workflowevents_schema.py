"""Ce que le moteur exige d'un modèle désigné par un `DEFINE EVENT`, et pourquoi.

Les deux règles ne viennent pas d'un goût de rigueur : elles viennent du MOTEUR, qui
valide le socle commun EN PLUS du schéma métier. Chaque refus est donc éprouvé deux fois
ici — une fois sur le portail, une fois sur le moteur lui-même — parce qu'une garde dont
on ne prouve pas qu'elle recouvre un vrai refus dérive en silence.

Depuis le 14/11/2026 ces règles portent sur la DÉCLARATION et non sur le fichier : un
modèle n'a aucune raison de les respecter tant qu'aucun type d'event ne le désigne, et
c'est pour cela qu'elles ne sont pas passées dans `datamodels.schema`.
"""

from __future__ import annotations

import pytest
from urban_workflow.exceptions import EventSchemaError
from urban_workflow.schemas import SchemaRegistry

from miles.datamodels.schema import parse_schema
from miles.workflowevents.schema import (
    SOCLE_NAMES,
    dedup_problems,
    payload_problems,
    socle_schema,
)

DEMANDE = """title: Demande soumise
type: object
required: [Montant]
properties:
  Montant: {type: number}
  Dossier: {$ref: "miles:/shared/dossier"}
"""

# Un payload tel qu'un émetteur l'envoie : le socle commun, plus le métier.
PAYLOAD = {"Name": "demande_soumise", "ExternalId": "DA-42", "Montant": 120}


def _codes(text: str) -> list[tuple[str, str]]:
    return [(p.path, p.code) for p in payload_problems(text, parse_schema(text))]


def _dedup_codes(text: str, keys: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(p.path, p.code) for p in dedup_problems(keys, parse_schema(text))]


def _engine_refuses(text: str, payload: dict[str, object]) -> str | None:
    """Le message du moteur sur ce payload, ou None s'il l'accepte."""
    registry = SchemaRegistry().add_yaml("ev", text)
    try:
        registry.validate("ev", payload)
    except EventSchemaError as exc:
        return str(exc)
    return None


class TestLeSocle:
    def test_le_socle_est_un_SCHEMA_lu_du_moteur_et_non_recopie(self) -> None:
        socle = socle_schema()

        assert set(socle["properties"]) == set(SOCLE_NAMES)
        assert {"Name", "Uuid", "ExternalId", "CreationDate", "EventDate", "DedupKey"} <= set(
            socle["properties"]
        )
        # Rendu en JSON Schema : l'écran le monte dans le même éditeur visuel que les
        # champs métier, et un agent y lit ce qu'une liste de noms aurait perdu.
        assert socle["type"] == "object"
        assert socle["required"] == ["Name"]
        assert socle["properties"]["Uuid"]["format"] == "uuid"

    def test_la_date_d_integration_est_annoncee_comme_posee_par_le_moteur(self) -> None:
        # `readOnly` du JSON Schema : c'est le moteur qui l'écrit à l'intégration, une
        # valeur de l'émetteur est ignorée. L'écran doit pouvoir le dire.
        socle = socle_schema()
        lecture_seule = {nom for nom, forme in socle["properties"].items() if forme.get("readOnly")}

        assert lecture_seule == {"IntegrationDate"}

    def test_le_socle_rendu_est_une_COPIE_du_dictionnaire_du_moteur(self) -> None:
        """Le moteur porte un singleton de module : le modifier changerait ce que
        validera la déclaration suivante. Discriminant — sans la copie, ce test rougit."""
        socle_schema()["properties"].pop("Name")

        assert "Name" in socle_schema()["properties"]


class TestLesRefusPropresAuPayload:
    FERME = """title: Demande
type: object
additionalProperties: false
properties:
  Montant: {type: number}
"""

    def test_un_schema_ferme_est_refuse(self) -> None:
        assert ("additionalProperties", "schema_ferme") in _codes(self.FERME)

    def test_et_le_moteur_l_aurait_refuse_pour_de_vrai(self) -> None:
        """La preuve que la garde recouvre un vrai refus, pas une préoccupation d'esthète."""
        message = _engine_refuses(self.FERME, PAYLOAD)
        assert message is not None
        assert "Additional properties are not allowed" in message
        assert "'Name'" in message

    def test_une_propriete_du_socle_redeclaree_est_refusee_en_la_nommant(self) -> None:
        text = "title: D\ntype: object\nproperties:\n  ExternalId: {type: integer}\n"
        assert ("properties.ExternalId", "propriete_du_socle") in _codes(text)

    def test_et_le_moteur_rendrait_le_payload_insatisfiable(self) -> None:
        # `ExternalId` en integer dans le métier, en string dans le socle : les DEUX
        # schémas s'appliquent, donc aucune valeur ne convient. Ni l'un ni l'autre des
        # documents ne paraît faux — c'est exactement ce qu'on refuse de déclarer.
        text = "title: D\ntype: object\nproperties:\n  ExternalId: {type: integer}\n"
        assert _engine_refuses(text, PAYLOAD) is not None
        assert _engine_refuses(text, {**PAYLOAD, "ExternalId": 42}) is not None


class TestLesClesDUnicite:
    def test_une_cle_du_modele_ou_du_socle_est_admise(self) -> None:
        """Le socle compte, et c'est le cas le plus courant : `UNIQUE (ExternalId)` ne
        nomme rien du modèle métier et reste la clé d'anti-doublon naturelle."""
        assert _dedup_codes(DEMANDE, ("Montant", "ExternalId")) == []

    def test_une_cle_qui_ne_designe_rien_est_refusee(self) -> None:
        """`compute_dedup_hash` compte une propriété absente comme vide : la clé donnerait
        le même hash pour TOUS les events, qui se dédoublonneraient les uns les autres."""
        assert _dedup_codes(DEMANDE, ("Inconnu",)) == [("unique.0", "cle_d_unicite_inconnue")]

    def test_une_cle_que_le_dsl_ne_sait_pas_ecrire_est_refusee_avant_la_propriete(self) -> None:
        """Mesuré : `UNIQUE (Mon-Champ)` rend « mismatched input '-' expecting {')', ','} ».
        Un artefact illisible fait échouer le chargement de tout le répertoire du moteur,
        donc ce refus tombe avant celui qui parle du modèle."""
        text = "title: D\ntype: object\nproperties:\n  Mon-Champ: {type: string}\n"
        assert _dedup_codes(text, ("Mon-Champ",)) == [("unique.0", "cle_non_ecrivable")]

    def test_la_position_de_la_cle_fautive_est_rendue(self) -> None:
        # L'ordre est une donnée : le refus doit dire LAQUELLE des clés, pas seulement
        # qu'il y en a une de mauvaise.
        assert _dedup_codes(DEMANDE, ("Montant", "Inconnu")) == [
            ("unique.1", "cle_d_unicite_inconnue")
        ]


class TestCeQuiEstAdmis:
    def test_un_modele_sans_propriete_metier_peut_porter_un_type_d_event(self) -> None:
        """Un `DEFINE EVENT` peut n'apporter que le socle — un nom, un `ExternalId`, une
        date — et déclencher une transition sur ce seul fait."""
        text = "title: Ping\ntype: object\nproperties: {}\n"

        assert payload_problems(text, parse_schema(text)) == []

    def test_un_payload_decrit_avec_un_renvoi_vers_un_modele_est_admis(self) -> None:
        schema = parse_schema(DEMANDE)

        assert payload_problems(DEMANDE, schema) == []
        assert schema.references == (("properties.Dossier.$ref", ("shared", "dossier")),)

    def test_le_moteur_accepte_le_payload_d_un_schema_ouvert(self) -> None:
        ouvert = (
            "title: D\ntype: object\nrequired: [Montant]\nproperties:\n  Montant: {type: number}\n"
        )
        assert _engine_refuses(ouvert, PAYLOAD) is None


@pytest.mark.parametrize("nom", sorted(SOCLE_NAMES))
def test_aucune_propriete_du_socle_n_est_inecrivable_en_cle_d_unicite(nom: str) -> None:
    """Toutes se nomment dans un `UNIQUE (…)`, et c'est MESURÉ sur le lexer installé : si
    une montée du moteur en ajoutait une que le DSL ne sait pas écrire, le portail la
    proposerait comme clé et l'artefact deviendrait illisible."""
    text = "title: D\ntype: object\nproperties: {}\n"

    assert _dedup_codes(text, (nom,)) == []
