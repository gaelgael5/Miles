from __future__ import annotations

from dataclasses import replace

from miles.sources.layout import MAX_BATCH, Entry, EntryModes, SourceDoc
from miles.sources.openapi import document

BRUT = {"type": "object", "properties": {"accountId": {"type": "string"}}}
WEB = Entry(
    "web",
    "pudo/import-crm",
    "import-crm",
    EntryModes(element=True, batch=True, file=True),
    "$.root[*]",
    False,
    100,
)
DOC = SourceDoc("integration-des-sites", "integration des sites", "sites", (WEB,))
SCHEMAS = {"pudo/import-crm": BRUT}


def test_one_method_per_ticked_mode_and_no_other() -> None:
    only_element = replace(WEB, modes=EntryModes(True, False, False))

    paths = document(replace(DOC, entries=(only_element,)), SCHEMAS, "pudo/site")["paths"]

    assert list(paths) == ["/ingest/integration-des-sites/import-crm"]


def test_the_three_modes_give_the_three_methods() -> None:
    paths = document(DOC, SCHEMAS, "pudo/site")["paths"]

    assert sorted(paths) == [
        "/ingest/integration-des-sites/import-crm",
        "/ingest/integration-des-sites/import-crm/batch",
        "/ingest/integration-des-sites/import-crm/file",
    ]


def test_the_batch_method_carries_the_ceiling_the_declaration_promises() -> None:
    batch = document(DOC, SCHEMAS, "pudo/site")["paths"][
        "/ingest/integration-des-sites/import-crm/batch"
    ]
    schema = batch["post"]["requestBody"]["content"]["application/json"]["schema"]

    assert schema["type"] == "array"
    assert schema["maxItems"] == MAX_BATCH


def test_the_file_method_takes_a_binary_part_not_json() -> None:
    content = document(DOC, SCHEMAS, "pudo/site")["paths"][
        "/ingest/integration-des-sites/import-crm/file"
    ]["post"]["requestBody"]["content"]

    assert list(content) == ["multipart/form-data"]
    assert content["multipart/form-data"]["schema"]["properties"]["file"]["format"] == "binary"


def test_the_file_method_says_how_it_will_read_and_write() -> None:
    """Le découpage et le lot d'écriture sont dans la description : ils se lisent."""
    description = document(DOC, SCHEMAS, "pudo/site")["paths"][
        "/ingest/integration-des-sites/import-crm/file"
    ]["post"]["description"]

    assert "$.root[*]" in description and "100" in description


def test_the_source_model_is_inlined_as_a_component_not_left_as_a_miles_uri() -> None:
    """Un « miles:/… » ne veut rien dire pour un visualiseur : il ne sait pas lire le dépôt."""
    spec = document(DOC, SCHEMAS, "pudo/site")
    element = spec["paths"]["/ingest/integration-des-sites/import-crm"]["post"]

    assert spec["components"]["schemas"]["pudo.import-crm"] == BRUT
    assert element["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/pudo.import-crm"
    }


def test_the_path_stays_the_same_when_a_second_entry_arrives() -> None:
    """Qualifié dès la première entrée : sinon un appelant déjà branché casserait."""
    alone = document(DOC, SCHEMAS, "pudo/site")["paths"]
    second = replace(WEB, source_model="pudo/site", modes=EntryModes(True, False, False))
    pair = document(replace(DOC, entries=(WEB, second)), SCHEMAS, "pudo/site")["paths"]

    assert "/ingest/integration-des-sites/import-crm" in alone
    assert "/ingest/integration-des-sites/import-crm" in pair
    assert "/ingest/integration-des-sites/site" in pair


def test_two_entries_of_the_same_model_are_told_apart_by_their_rank() -> None:
    twins = (WEB, replace(WEB, modes=EntryModes(True, False, False)))

    paths = document(replace(DOC, entries=twins), SCHEMAS, "pudo/site")["paths"]

    assert "/ingest/integration-des-sites/import-crm-1" in paths
    assert "/ingest/integration-des-sites/import-crm-2" in paths


def test_a_source_without_entry_promises_nothing_but_is_still_a_document() -> None:
    spec = document(replace(DOC, entries=()), SCHEMAS, "pudo/site")

    assert spec["paths"] == {}
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "integration des sites"


def test_an_unknown_source_model_leaves_the_body_open_rather_than_a_dangling_reference() -> None:
    """Le modèle manque : on ne renvoie pas vers un composant qui n'existe pas."""
    spec = document(DOC, {}, "pudo/site")
    element = spec["paths"]["/ingest/integration-des-sites/import-crm"]["post"]

    assert spec["components"]["schemas"] == {}
    assert element["requestBody"]["content"]["application/json"]["schema"] == {}
