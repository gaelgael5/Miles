from __future__ import annotations

from typing import Any

import pytest

from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError, load_yaml
from miles.datamodels.navigate import kind_at
from miles.datamodels.schema import (
    DIALECT,
    draft,
    model_id,
    normalized,
    parse_schema,
    references_in,
    target_of,
)

COLIS = """title: Colis
type: object
required: [reference]
properties:
  reference: {type: string, format: uuid}
  etat: {type: string, enum: [depose, remis]}
  destinataire: {$ref: "miles:/shared/personne"}
  etiquettes: {type: array, items: {type: string}}
  adresse:
    type: object
    properties:
      ville: {type: string}
  tarif: {$ref: "#/$defs/tarif"}
$defs:
  tarif: {type: number}
"""


def _codes(text: str) -> list[tuple[str, str]]:
    with pytest.raises(ModelGrammarError) as refused:
        parse_schema(text)
    return [(p.path, p.code) for p in refused.value.problems]


def test_a_json_schema_model_is_read_with_its_title_properties_and_references() -> None:
    schema = parse_schema(COLIS)

    assert schema.title == "Colis"
    assert list(schema.properties) == [
        "reference",
        "etat",
        "destinataire",
        "etiquettes",
        "adresse",
        "tarif",
    ]
    assert schema.references == (("properties.destinataire.$ref", ("shared", "personne")),)
    assert schema.empty is False


def test_every_meta_schema_mistake_is_named_with_its_place() -> None:
    codes = _codes(
        "type: object\nproperties:\n  a: {type: texte}\n  b: {type: string, minLength: -1}\n"
    )

    assert ("properties.a.type", "schema_invalide") in codes
    assert ("properties.b.minLength", "schema_invalide") in codes
    assert len(codes) >= 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("type: array\n", ("type", "objet_attendu")),
        ("- a\n", ("", "document_non_objet")),
        (
            "type: object\nproperties:\n  a: {$ref: 'https://ailleurs/x.json'}\n",
            ("properties.a.$ref", "reference_externe"),
        ),
    ],
    ids=["racine-non-objet", "liste", "ref-externe"],
)
def test_miles_rules_come_on_top_of_the_meta_schema(text: str, expected: tuple[str, str]) -> None:
    assert expected in _codes(text)


def test_unreadable_yaml_and_duplicate_keys_are_syntax_errors() -> None:
    with pytest.raises(ModelSyntaxError):
        parse_schema("type: object\nproperties: [\n")
    with pytest.raises(ModelSyntaxError):
        load_yaml("type: object\ntype: array\n")


def test_the_system_sets_schema_and_id_first_whatever_the_client_wrote() -> None:
    text = normalized("$id: 'miles:/shared/autre'\ntitle: Colis\ntype: object\n", "suivi", "colis")

    assert text.startswith(f"$schema: {DIALECT}\n$id: miles:/domains/suivi/colis\n")
    assert parse_schema(text).identifier == model_id("suivi", "colis")


def test_a_declared_model_is_an_empty_object_draft() -> None:
    schema = parse_schema(draft("shared", "personne", "Personne livrée"))

    assert (schema.title, schema.empty, schema.properties) == ("Personne livrée", True, {})


@pytest.mark.parametrize(
    ("ref", "target"),
    [
        ("miles:/shared/personne", ("shared", "personne")),
        ("miles:/domains/suivi/colis#/$defs/x", ("suivi", "colis")),
        ("#/$defs/x", None),
        ("miles:/ailleurs/x", None),
    ],
)
def test_references_name_a_model_by_its_uri(ref: str, target: tuple[str, str] | None) -> None:
    assert target_of(ref) == target


def test_references_are_found_even_in_a_model_broken_outside_miles() -> None:
    broken = "type: texte\nproperties:\n  a: {$ref: 'miles:/shared/personne'}\n"

    assert references_in(broken) == {("shared", "personne")}
    assert references_in("pas: [du yaml") == set()


PERSONNE = load_yaml("type: object\nproperties:\n  nom: {type: string}\n  parent: {$ref: '#'}\n")


async def _read(path: str) -> str | None:
    return (
        "type: object\nproperties:\n  nom: {type: string}\n"
        if path.endswith("personne.yaml")
        else None
    )


@pytest.mark.parametrize(
    ("keys", "kind"),
    [
        (["reference"], "string"),
        (["etiquettes"], "array"),
        (["adresse"], "object"),
        (["adresse", "ville"], "string"),
        (["destinataire", "nom"], "string"),
        (["tarif"], "number"),
        (["absente"], None),
    ],
)
async def test_a_property_kind_is_found_through_objects_and_references(
    keys: list[str], kind: str | None
) -> None:
    root: Any = load_yaml(COLIS)

    assert await kind_at(_read, "suivi", root, keys) == kind


async def test_a_self_reference_does_not_loop_forever() -> None:
    assert await kind_at(_read, "shared", PERSONNE, ["parent", "parent", "nom"]) == "string"
    looping = load_yaml("type: object\nproperties:\n  a: {$ref: '#/properties/a'}\n")
    assert await kind_at(_read, "shared", looping, ["a"]) is None
