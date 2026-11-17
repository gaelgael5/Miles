"""Les types d'event de workflow par la surface MCP : un agent les déclare et les relit.

Ce que ces tests tiennent, et qu'aucun test unitaire ne tient : qu'une déclaration faite
par un AGENT arrive dans le dépôt sous la forme que le PARSEUR DU MOTEUR relit — la même
que celle de l'écran —, que les refus portent les mêmes noms d'un canal à l'autre, et que
la frontière des droits (clé seule, lecteur, branche racine) s'applique ici aussi.

Le consommateur de l'artefact n'est pas Miles : chaque écriture est donc relue par
`urban_workflow`, jamais comparée à un texte attendu.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.datamodels.schema import normalized as normalized_model
from tests.integration.mcp_stack import McpForge, issue_key, open_mcp_forge

pytestmark = pytest.mark.integration

WS = {"workspace_id": "retrait"}
EDIT = WS | {"branch": "edition"}
ARTEFACT = "shared/shared.wf"

DEMANDE = normalized_model(
    "title: Demande\ntype: object\nproperties:\n  Montant: {type: number}\n",
    "shared",
    "demande",
)
# Un modèle de DOMAINE : un périmètre transverse ne peut pas le désigner sans cesser
# d'être transverse, et c'est ce que `portee_du_modele` refuse.
SUIVI = normalized_model(
    "title: Suivi\ntype: object\nproperties:\n  Etat: {type: string}\n",
    "suivi",
    "suivi",
)
DECLARATION = {
    "scope": "shared",
    "name": "demande_soumise",
    "label": "Demande soumise",
    "model_scope": "shared",
    "model_name": "demande",
}


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def _model(m: McpForge, scope: str, name: str, content: str) -> None:
    await m.ok("create_schema", EDIT | {"scope": scope, "name": name, "content": content})


async def test_a_type_is_declared_listed_replaced_and_deleted_on_a_child_branch(
    m: McpForge,
) -> None:
    await _model(m, "shared", "demande", DEMANDE)

    declared = await m.ok("declare_event_type", EDIT | DECLARATION | {"unique": ["Montant"]})
    replay = await m.ok("declare_event_type", EDIT | DECLARATION | {"unique": ["Montant"]})
    listed = await m.ok("list_event_types", EDIT)
    replaced = await m.ok(
        "replace_event_type",
        EDIT | DECLARATION | {"label": "Demande reçue", "unique": ["Montant", "ExternalId"]},
    )
    written = await m.forge.file(ARTEFACT)
    deleted = await m.ok("delete_event_type", EDIT | {"scope": "shared", "name": "demande_soumise"})

    assert declared["commit"] and declared["unchanged"] is False
    assert declared | {"commit": None, "unchanged": True} == replay | {"commit": None}
    assert listed == [
        {
            "scope": "shared",
            "name": "demande_soumise",
            "label": "Demande soumise",
            "path": ARTEFACT,
            "model": "shared/models/demande.yaml",
            "model_scope": "shared",
            "model_name": "demande",
            "unique": ["Montant"],
            "model_missing": False,
        }
    ]
    # L'ordre des clés est une DONNÉE : le moteur dérive le hash d'anti-doublon par
    # concaténation, donc le relire trié aurait changé l'anti-doublon sans rien dire.
    assert (replaced["label"], replaced["unique"]) == ("Demande reçue", ["Montant", "ExternalId"])
    assert written is not None
    script = WorkflowScriptParser.parse_string(written, ARTEFACT)
    assert [(e.line, e.message) for e in script.errors] == []
    assert script.is_fragment and "AS @shared.demande" in written
    # L'artefact disparaît avec sa dernière déclaration : vide, il serait une erreur de
    # syntaxe et ferait échouer le chargement de tout le répertoire.
    assert deleted["commit"] and await m.forge.file(ARTEFACT) is None
    # Le MODÈLE reste : c'en est un comme un autre, et seul `delete_schema` le supprime.
    assert await m.forge.file("shared/models/demande.yaml") is not None


async def test_the_refusals_of_a_declaration_are_named_as_the_screen_names_them(
    m: McpForge,
) -> None:
    await _model(m, "shared", "demande", DEMANDE)
    await m.ok("create_domain", EDIT | {"name": "suivi"})
    await _model(m, "suivi", "suivi", SUIVI)
    await m.ok("declare_event_type", EDIT | DECLARATION)

    taken = await m.refused("declare_event_type", EDIT | DECLARATION | {"label": "Autre"})
    elsewhere = await m.refused(
        "declare_event_type",
        EDIT | DECLARATION | {"scope": "suivi", "model_scope": "suivi", "model_name": "suivi"},
    )
    no_domain = await m.refused(
        "declare_event_type",
        EDIT | DECLARATION | {"scope": "absent", "name": "autre_type"},
    )
    out_of_scope = await m.refused(
        "declare_event_type",
        EDIT | DECLARATION | {"name": "hors_portee", "model_scope": "suivi", "model_name": "suivi"},
    )
    no_model = await m.refused(
        "declare_event_type", EDIT | DECLARATION | {"name": "sans_modele", "model_name": "absent"}
    )
    hyphen = await m.refused("declare_event_type", EDIT | DECLARATION | {"name": "demande-recue"})
    unknown_key = await m.refused(
        "declare_event_type",
        EDIT | DECLARATION | {"name": "cle_inventee", "unique": ["Inexistante"]},
    )

    assert taken == {"code": "nom_pris"}
    # Le même nom dans deux périmètres rend inchargeable tout script qui inclut les deux :
    # refusé au geste plutôt qu'au chargement.
    assert elsewhere == {"code": "nom_pris_ailleurs"}
    assert no_domain == {"code": "domaine_inconnu"}
    assert out_of_scope == {"code": "portee_du_modele"}
    assert no_model["code"] == "declaration_non_conforme"
    assert {p["code"] for p in no_model["problems"]} == {"modele_inconnu"}
    # Le DSL du moteur ne sait pas écrire `DEFINE EVENT demande-recue` : refusé à la
    # saisie, et non au chargement d'un script.
    assert hyphen == {"code": "champ_invalide", "champ": "name", "raison": None}
    assert unknown_key["code"] == "declaration_non_conforme"


async def test_an_unknown_type_names_those_that_exist(m: McpForge) -> None:
    await _model(m, "shared", "demande", DEMANDE)
    await m.ok("declare_event_type", EDIT | DECLARATION)
    target = {"scope": "shared", "name": "jamais_declare"}

    replacing = await m.refused("replace_event_type", EDIT | DECLARATION | target)
    deleting = await m.refused("delete_event_type", EDIT | target)

    expected = {
        "code": "evenement_inconnu",
        "evenement": "shared/jamais_declare",
        "existants": ["shared/demande_soumise"],
    }
    assert (replacing, deleting) == (expected, expected)


async def test_a_declaration_whose_model_is_absent_is_listed_as_missing_not_hidden(
    m: McpForge,
) -> None:
    """Ce qui bloquera l'enregistrement d'une version se VOIT dans la liste.

    La déclaration orpheline est SEMÉE hors de Miles : par ses propres gestes, elle est
    impossible — la déclaration refuse un modèle absent, et `delete_schema` refuse un
    modèle qu'une déclaration désigne. Les deux gardes sont vérifiées ici même.
    """
    await m.forge.seed(
        {ARTEFACT: "FRAGMENT NAME shared\nDEFINE EVENT orphelin 'Orphelin' AS @shared.absent;\n"}
    )

    listed = await m.ok("list_event_types", EDIT)

    assert [(d["name"], d["model_missing"], d["model"]) for d in listed] == [
        ("orphelin", True, "shared/models/absent.yaml")
    ]


async def test_the_model_of_a_declared_type_cannot_be_deleted_by_the_schema_primitive(
    m: McpForge,
) -> None:
    """La garde qui rend l'orpheline ci-dessus impossible par les gestes de Miles."""
    await _model(m, "shared", "demande", DEMANDE)
    await m.ok("declare_event_type", EDIT | DECLARATION)

    used = await m.refused("delete_schema", EDIT | {"scope": "shared", "name": "demande"})

    assert used["code"] == "modele_utilise" and ARTEFACT in str(used["par"])


async def test_an_artefact_touched_outside_miles_is_refused_with_the_engine_positions(
    m: McpForge,
) -> None:
    await m.forge.seed({ARTEFACT: "FRAGMENT NAME shared\nDEFINE EVENT ceci n'est pas du DSL\n"})

    listing = await m.refused("list_event_types", EDIT)
    declaring = await m.refused("declare_event_type", EDIT | DECLARATION)

    assert listing["code"] == "artefact_illisible"
    assert listing["problems"] and listing["problems"][0]["line"] >= 1
    # Le même code par les deux canaux : un agent qui l'apprend ici le reconnaît sur
    # l'écran, et l'écriture ne passe pas par-dessus ce qu'on n'a pas su relire.
    assert declaring["code"] == "artefact_illisible"


async def test_rights_apply_to_declarations_as_they_do_to_schemas(m: McpForge) -> None:
    await _model(m, "shared", "demande", DEMANDE)
    reader = await issue_key(m.forge, {"retrait": "lecture"}, label="Lecteur")
    as_reader: dict[str, Any] = {"Authorization": f"Bearer {reader['secret']}"}
    key_only = {"Authorization": f"Bearer {m.secret}"}

    alone = await m.refused("declare_event_type", EDIT | DECLARATION, headers=key_only)
    denied = await m.refused("declare_event_type", EDIT | DECLARATION, headers=as_reader)
    root = await m.refused("declare_event_type", WS | DECLARATION | {"branch": "atelier"})
    read_root = await m.ok("list_event_types", WS)

    assert alone == {"code": "personne_requise"}
    assert denied == {"code": "droit_insuffisant", "workspace": "retrait", "droit": "lecture"}
    assert root == {"code": "branche_racine_lecture_seule", "branches": ["edition"]}
    assert read_root == []
