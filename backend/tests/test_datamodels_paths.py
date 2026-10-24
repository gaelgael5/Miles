from __future__ import annotations

from miles.datamodels.paths import MAX_PATHS, PathEntry, paths_of


def _paths(schema: object) -> list[str]:
    return [e.path for e in paths_of(schema)]


def test_each_property_gives_a_path_from_the_root() -> None:
    schema = {"type": "object", "properties": {"Name": {"type": "string"}}}

    assert paths_of(schema) == [PathEntry("$.Name", "string", "")]


def test_an_array_is_indexed_not_starred() -> None:
    """La forme qu'on écrit vraiment dans un template, et celle de l'exemple d'origine."""
    schema = {
        "type": "object",
        "properties": {
            "Account": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"PickupReference": {"type": "string"}},
                },
            }
        },
    }

    assert _paths(schema) == ["$.Account", "$.Account[0]", "$.Account[0].PickupReference"]


def test_the_type_and_the_title_travel_with_the_path() -> None:
    schema = {
        "type": "object",
        "properties": {"Name": {"type": "string", "title": "Raison sociale"}},
    }

    assert paths_of(schema) == [PathEntry("$.Name", "string", "Raison sociale")]


def test_a_property_without_a_type_is_announced_as_a_plain_value() -> None:
    # Les champs que l'échantillon n'a jamais remplis sortent sans type (détente du 24/10).
    schema = {"type": "object", "properties": {"StorageDepth": {}}}

    assert paths_of(schema)[0].kind == "valeur"


def test_a_union_shows_both_types() -> None:
    schema = {"type": "object", "properties": {"Ref": {"type": ["string", "null"]}}}

    assert paths_of(schema)[0].kind == "string|null"


def test_a_key_that_would_break_the_path_is_quoted() -> None:
    schema = {"type": "object", "properties": {"mon.champ": {"type": "string"}}}

    assert _paths(schema) == ['$["mon.champ"]']


def test_an_internal_reference_is_followed() -> None:
    schema = {
        "type": "object",
        "$defs": {"ligne": {"type": "object", "properties": {"Rue": {"type": "string"}}}},
        "properties": {"Adresse": {"$ref": "#/$defs/ligne"}},
    }

    assert _paths(schema) == ["$.Adresse", "$.Adresse.Rue"]


def test_a_reference_to_another_model_stops_there() -> None:
    """Le service les résout avant d'appeler ; parvenu ici, on ne descend pas."""
    schema = {"type": "object", "properties": {"Colis": {"$ref": "miles:/shared/colis"}}}

    assert _paths(schema) == ["$.Colis"]


def test_a_model_that_references_itself_stops_instead_of_looping() -> None:
    schema = {
        "type": "object",
        "$defs": {
            "noeud": {
                "type": "object",
                "properties": {"Nom": {"type": "string"}, "Fils": {"$ref": "#/$defs/noeud"}},
            }
        },
        "properties": {"Racine": {"$ref": "#/$defs/noeud"}},
    }

    found = _paths(schema)

    assert "$.Racine.Nom" in found
    assert len(found) < MAX_PATHS


def test_what_is_not_a_schema_gives_nothing() -> None:
    assert paths_of("texte") == []
    assert paths_of(None) == []
