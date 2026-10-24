from __future__ import annotations

import pytest
import yaml

from miles.datamodels.grammar import ModelSyntaxError
from miles.datamodels.inference import (
    SampleNotAnObjectError,
    infer,
    infer_root,
    read_sample,
)
from miles.datamodels.schema import normalized, parse_schema


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


def test_a_list_at_the_root_describes_one_of_its_elements() -> None:
    """Un export est une LISTE d'exemplaires ; le modèle, lui, décrit l'exemplaire.

    Sans ce dégagement, l'import rendait `type: array`, que la grammaire refuse aussitôt
    (« objet_attendu ») : le modèle était fabriqué pour être rejeté.
    """
    schema, unwrapped = infer_root([{"Name": "a"}, {"Name": "b", "Ref": "215"}])

    assert unwrapped is True
    assert schema == {
        "type": "object",
        "properties": {"Name": {"type": "string"}, "Ref": {"type": "string"}},
    }


def test_an_object_at_the_root_is_taken_as_is() -> None:
    schema, unwrapped = infer_root({"Name": "a"})

    assert unwrapped is False
    assert schema["type"] == "object"


@pytest.mark.parametrize("sample", [[], "texte", 3, None, [1, 2]])
def test_a_sample_that_holds_no_object_is_refused_rather_than_shaped(sample: object) -> None:
    # Mieux vaut un refus nommé qu'un schéma que la grammaire rejettera ensuite.
    with pytest.raises(SampleNotAnObjectError):
        infer_root(sample)


def test_the_real_export_gives_a_usable_model() -> None:
    """L'échantillon qui a révélé le défaut : deux points relais, enveloppés dans une liste."""
    sample = [
        {
            "Account": [{"Name": "Barale", "ActivationDate": "2020-11-16"}],
            "Period": [{"StartDate": "2026-07-24"}],
            "ParkManager": [],
        },
        {"Account": [{"Name": "Menditto", "ActivationDate": "2020-10-15"}], "Period": []},
    ]

    schema, unwrapped = infer_root(sample)

    assert unwrapped is True
    assert schema["type"] == "object"
    account = schema["properties"]["Account"]["items"]["properties"]
    assert account["ActivationDate"] == {"type": "string", "format": "date"}
    # Period est vide dans un exemplaire et peuplé dans l'autre : la fusion garde la forme.
    assert schema["properties"]["Period"]["items"]["properties"]["StartDate"]["format"] == "date"
    # ParkManager n'est jamais peuplé : on ne lui invente pas d'éléments.
    assert schema["properties"]["ParkManager"] == {"type": "array"}


@pytest.mark.parametrize(
    "sample",
    [
        [{"Account": [{"Name": "a", "Seen": "2026-10-24T08:00:00Z"}], "Tags": []}],
        {"nom": "a", "liste": [1, "deux", None], "imbrique": {"a": {"b": [True]}}},
        [{"a": 1}, {"a": "x"}],
    ],
)
def test_what_the_inference_produces_is_accepted_by_the_grammar(sample: object) -> None:
    """La garde qui manquait : un schéma déduit doit passer la validation de Miles.

    Le premier import rendait `type: array` à la racine et le produit le refusait — le
    défaut n'avait été vu qu'à l'usage, faute de ce bouclage (Gael, 24/10/2026).
    """
    schema, _ = infer_root(sample)
    text = yaml.safe_dump({"title": "essai", **schema}, allow_unicode=True, sort_keys=False)

    # Ne lève pas : c'est tout ce qu'on demande.
    parse_schema(normalized(text, "shared", "essai"))
