"""Le schéma d'un événement : ce que le portail refuse, et pourquoi le moteur l'aurait refusé.

Les deux règles propres aux événements ne viennent pas d'un goût de rigueur : elles
viennent du MOTEUR, qui valide le socle commun EN PLUS du schéma métier. Chaque refus est
donc éprouvé deux fois ici — une fois sur le portail, une fois sur le moteur lui-même —
parce qu'une garde dont on ne prouve pas qu'elle recouvre un vrai refus dérive en silence.
"""

from __future__ import annotations

import pytest
import yaml
from urban_workflow.exceptions import EventSchemaError
from urban_workflow.schemas import SchemaRegistry

from miles.datamodels.grammar import ModelGrammarError
from miles.datamodels.schema import DIALECT
from miles.workflowevents.schema import (
    SOCLE_NAMES,
    draft,
    normalized,
    parse_event_schema,
    socle_fields,
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
    with pytest.raises(ModelGrammarError) as refused:
        parse_event_schema(text)
    return [(p.path, p.code) for p in refused.value.problems]


def _engine_refuses(text: str, payload: dict[str, object]) -> str | None:
    """Le message du moteur sur ce payload, ou None s'il l'accepte."""
    registry = SchemaRegistry().add_yaml("ev", text)
    try:
        registry.validate("ev", payload)
    except EventSchemaError as exc:
        return str(exc)
    return None


class TestLeSocle:
    def test_le_socle_est_lu_du_moteur_et_non_recopie(self) -> None:
        noms = {nom for nom, _, _ in socle_fields()}
        assert noms == set(SOCLE_NAMES)
        assert {"Name", "Uuid", "ExternalId", "CreationDate", "EventDate", "DedupKey"} <= noms

    def test_la_date_d_integration_est_annoncee_comme_posee_par_le_moteur(self) -> None:
        # `readOnly` du JSON Schema : c'est le moteur qui l'écrit à l'intégration, une
        # valeur de l'émetteur est ignorée. L'écran doit pouvoir le dire.
        lecture_seule = {nom for nom, _, seule in socle_fields() if seule}
        assert lecture_seule == {"IntegrationDate"}


class TestLesRefusPropresAuxEvenements:
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
        # documents ne paraît faux — c'est exactement ce qu'on refuse d'écrire.
        text = "title: D\ntype: object\nproperties:\n  ExternalId: {type: integer}\n"
        assert _engine_refuses(text, PAYLOAD) is not None
        assert _engine_refuses(text, {**PAYLOAD, "ExternalId": 42}) is not None


class TestCeQuiEstAdmis:
    def test_un_evenement_sans_propriete_metier_est_admis(self) -> None:
        """Et ce n'est PAS un brouillon, à la différence d'un modèle.

        Un `DEFINE EVENT` peut n'apporter que le socle — un nom, un `ExternalId`, une
        date — et déclencher une transition sur ce seul fait.
        """
        schema = parse_event_schema("title: Ping\ntype: object\nproperties: {}\n")
        assert schema.properties == {}
        assert schema.empty is True

    def test_un_evenement_decrit_son_payload_avec_un_modele(self) -> None:
        schema = parse_event_schema(DEMANDE)
        assert schema.title == "Demande soumise"
        assert schema.references == (("properties.Dossier.$ref", ("shared", "dossier")),)

    def test_le_moteur_accepte_le_payload_d_un_schema_ouvert(self) -> None:
        ouvert = (
            "title: D\ntype: object\nrequired: [Montant]\nproperties:\n  Montant: {type: number}\n"
        )
        assert _engine_refuses(ouvert, PAYLOAD) is None


class TestLEnregistrement:
    def test_le_systeme_pose_le_dialecte_et_l_id_de_l_evenement(self) -> None:
        written = yaml.safe_load(normalized(DEMANDE, "shared", "demande_soumise"))

        assert written["$schema"] == DIALECT
        assert written["$id"] == "miles:/events/shared/demande_soumise"
        assert written["title"] == "Demande soumise"
        assert list(written)[:2] == ["$schema", "$id"]

    def test_un_evenement_declare_est_un_objet_sans_propriete(self) -> None:
        written = yaml.safe_load(draft("achats", "validation", "Validation accordée"))

        assert written["$id"] == "miles:/events/domains/achats/validation"
        assert written["title"] == "Validation accordée"
        assert written["properties"] == {}
