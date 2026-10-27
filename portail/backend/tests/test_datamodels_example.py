from __future__ import annotations

import pytest

from miles.datamodels.example import MAX_DEPTH, example_of


def test_a_string_carries_the_name_of_its_property() -> None:
    schema = {"type": "object", "properties": {"Name": {"type": "string"}}}

    assert example_of(schema) == {"Name": "Name"}


def test_numbers_are_zero_and_booleans_are_false() -> None:
    schema = {
        "type": "object",
        "properties": {
            "Latitude": {"type": "number"},
            "Count": {"type": "integer"},
            "IsActive": {"type": "boolean"},
            "Nothing": {"type": "null"},
        },
    }

    assert example_of(schema) == {"Latitude": 0, "Count": 0, "IsActive": False, "Nothing": None}


def test_an_array_always_carries_one_element() -> None:
    """Un tableau vide ne montrerait pas ce qu'il contient — et c'est ce qu'on vient voir."""
    schema = {
        "type": "object",
        "properties": {
            "Account": {
                "type": "array",
                "items": {"type": "object", "properties": {"Name": {"type": "string"}}},
            }
        },
    }

    assert example_of(schema) == {"Account": [{"Name": "Name"}]}


def test_an_array_of_strings_carries_the_name_of_the_array() -> None:
    schema = {
        "type": "object",
        "properties": {"Tags": {"type": "array", "items": {"type": "string"}}},
    }

    assert example_of(schema) == {"Tags": ["Tags"]}


def test_an_array_without_described_items_stays_empty() -> None:
    # Inventer un élément mentirait sur sa forme : on ne sait pas ce qu'il contient.
    schema = {"type": "object", "properties": {"ParkManager": {"type": "array"}}}

    assert example_of(schema) == {"ParkManager": []}


def test_nesting_is_followed_to_the_bottom() -> None:
    schema = {
        "type": "object",
        "properties": {
            "Address": {
                "type": "object",
                "properties": {
                    "City": {"type": "string"},
                    "Lines": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }

    assert example_of(schema) == {"Address": {"City": "City", "Lines": ["Lines"]}}


def test_a_union_shows_the_useful_type_not_the_absence() -> None:
    schema = {"type": "object", "properties": {"Ref": {"type": ["null", "string"]}}}

    # « null » d'abord décrirait un gabarit vide là où le modèle accepte une chaîne.
    assert example_of(schema) == {"Ref": "Ref"}


def test_a_union_of_nothing_but_null_stays_null() -> None:
    schema = {"type": "object", "properties": {"Ref": {"type": ["null"]}}}

    assert example_of(schema) == {"Ref": None}


def test_an_internal_reference_is_followed() -> None:
    schema = {
        "type": "object",
        "$defs": {"ligne": {"type": "object", "properties": {"Rue": {"type": "string"}}}},
        "properties": {"Adresse": {"$ref": "#/$defs/ligne"}},
    }

    assert example_of(schema) == {"Adresse": {"Rue": "Rue"}}


def test_a_reference_to_another_model_leaves_the_place_empty() -> None:
    """Les `miles:/…` sont résolus par le service avant d'arriver ici ; sinon, rien."""
    schema = {"type": "object", "properties": {"Colis": {"$ref": "miles:/shared/colis"}}}

    assert example_of(schema) == {"Colis": None}


def test_a_model_that_references_itself_stops_instead_of_overflowing() -> None:
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

    example = example_of(schema)

    # Pas de débordement de pile : on descend jusqu'au plafond puis on s'arrête.
    node = example["Racine"]
    for _ in range(MAX_DEPTH - 2):
        assert isinstance(node, dict)
        node = node["Fils"]


def test_a_property_without_a_type_falls_back_to_its_name() -> None:
    schema = {"type": "object", "properties": {"Libre": {}}}

    assert example_of(schema) == {"Libre": "Libre"}


@pytest.mark.parametrize("schema", [None, "texte", 3, []])
def test_what_is_not_a_schema_gives_nothing(schema: object) -> None:
    assert example_of(schema) is None
