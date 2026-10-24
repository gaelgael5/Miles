from __future__ import annotations

import pytest

from miles.datamodels.grammar import ModelSyntaxError
from miles.datamodels.inference import infer, read_sample


def test_an_object_becomes_properties_without_requiring_any_of_them() -> None:
    schema = infer({"nom": "Gaël", "age": 41})

    # Parti pris du 24/10/2026 : un échantillon décrit, il n'exige pas.
    assert schema == {
        "type": "object",
        "properties": {"nom": {"type": "string"}, "age": {"type": "integer"}},
    }
    assert "required" not in schema


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, {"type": "boolean"}),
        # Avant l'entier : en Python, un booléen EST un entier.
        (False, {"type": "boolean"}),
        (3, {"type": "integer"}),
        (3.5, {"type": "number"}),
        (None, {"type": "null"}),
        ("texte", {"type": "string"}),
    ],
)
def test_each_scalar_gives_its_type(value: object, expected: dict[str, str]) -> None:
    assert infer(value) == expected


@pytest.mark.parametrize(
    ("value", "fmt"),
    [
        ("2026-10-24", "date"),
        ("2026-10-24T08:30:00Z", "date-time"),
        ("2026-10-24 08:30:00+02:00", "date-time"),
        ("08:30:00", "time"),
        ("8f14e45f-ceea-467a-9c2b-5f1d0e3a7b21", "uuid"),
        ("gael@example.org", "email"),
        ("https://example.org/a?b=1", "uri"),
    ],
)
def test_a_recognisable_string_carries_its_format(value: str, fmt: str) -> None:
    assert infer(value) == {"type": "string", "format": fmt}


def test_an_ordinary_string_carries_no_format() -> None:
    assert infer("12 rue des Lilas") == {"type": "string"}


def test_an_empty_array_says_nothing_about_its_items() -> None:
    assert infer([]) == {"type": "array"}


def test_an_array_merges_every_element_not_only_the_first() -> None:
    """Un second élément plus riche doit entrer dans le schéma, sinon il s'y ferait refuser."""
    schema = infer([{"nom": "a"}, {"nom": "b", "age": 2}])

    assert schema == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"nom": {"type": "string"}, "age": {"type": "integer"}},
        },
    }


def test_elements_of_irreconcilable_types_are_enumerated() -> None:
    assert infer([1, "a"]) == {"type": "array", "items": {"type": ["integer", "string"]}}


def test_a_null_among_values_is_kept_as_a_possible_type() -> None:
    assert infer(["a", None]) == {"type": "array", "items": {"type": ["string", "null"]}}


def test_disagreeing_formats_drop_the_format_rather_than_pick_one() -> None:
    schema = infer(["2026-10-24", "gael@example.org"])

    # Deux formats incompatibles : en garder un mentirait sur l'autre. Et le type reste
    # une chaîne simple, pas une liste d'un seul élément.
    assert schema == {"type": "array", "items": {"type": "string"}}


def test_nesting_is_followed_to_the_bottom() -> None:
    schema = infer({"colis": {"suivi": [{"etat": "remis", "le": "2026-10-24"}]}})

    assert schema["properties"]["colis"]["properties"]["suivi"]["items"]["properties"]["le"] == {
        "type": "string",
        "format": "date",
    }


def test_json_and_yaml_samples_give_the_same_schema() -> None:
    from_json = read_sample('{"nom": "Gaël", "tags": ["a"]}', "json")
    from_yaml = read_sample("nom: Gaël\ntags:\n  - a\n", "yaml")

    assert infer(from_json) == infer(from_yaml)


def test_malformed_json_names_where_it_breaks() -> None:
    with pytest.raises(ModelSyntaxError) as caught:
        read_sample('{"nom": }', "json")

    assert caught.value.line is not None


def test_an_unknown_format_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="format inconnu"):
        read_sample("{}", "xml")
