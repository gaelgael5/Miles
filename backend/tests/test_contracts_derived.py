from __future__ import annotations

from typing import Any

import pytest
import yaml

from miles.contracts.derived import (
    MAX_DEPTH,
    DerivationError,
    derive_models,
    model_name,
)


def _doc(schemas: dict[str, Any], openapi: str = "3.0.3") -> dict[str, Any]:
    return {
        "openapi": openapi,
        "info": {"title": "t", "version": "1"},
        "components": {"schemas": schemas},
    }


def _derived(schemas: dict[str, Any], openapi: str = "3.0.3") -> dict[str, dict[str, Any]]:
    models = derive_models(_doc(schemas, openapi), "materiel", 2)
    return {m.name: yaml.safe_load(m.content) for m in models}


def _codes(schemas: dict[str, Any], openapi: str = "3.0.3") -> list[tuple[str, str]]:
    with pytest.raises(DerivationError) as raised:
        derive_models(_doc(schemas, openapi), "materiel", 2)
    return [(p.path, p.code) for p in raised.value.problems]


def test_each_schema_becomes_a_model_under_its_contract_version_with_refs_rewritten() -> None:
    models = derive_models(
        _doc(
            {
                "PickupPoint": {
                    "type": "object",
                    "properties": {
                        "address": {"$ref": "#/components/schemas/Address"},
                        "city": {"$ref": "#/components/schemas/Address/properties/city"},
                    },
                },
                "Address": {"title": "Adresse", "type": "object", "properties": {"city": {}}},
            }
        ),
        "materiel",
        2,
    )

    by_name = {m.name: m for m in models}
    point = yaml.safe_load(by_name["pickup-point"].content)
    assert by_name["pickup-point"].path == "contracts/materiel/models/v2/pickup-point.yaml"
    assert by_name["pickup-point"].source == "PickupPoint"
    assert list(point)[:3] == ["$schema", "$id", "title"]
    assert point["$id"] == "miles:/contracts/materiel/v2/pickup-point"
    # Sans `title` dans le contrat, le modèle porte le nom d'origine du schéma.
    assert point["title"] == "PickupPoint"
    assert yaml.safe_load(by_name["address"].content)["title"] == "Adresse"
    assert point["properties"]["address"] == {"$ref": "miles:/contracts/materiel/v2/address"}
    assert point["properties"]["city"] == {
        "$ref": "miles:/contracts/materiel/v2/address#/properties/city"
    }


def test_a_contract_without_schemas_derives_nothing() -> None:
    assert derive_models({"openapi": "3.1.0", "info": {}, "paths": {}}, "materiel", 1) == []


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"type": "string", "nullable": True}, {"type": ["string", "null"]}),
        (
            {"type": "string", "enum": ["a", "b"], "nullable": True},
            {"type": ["string", "null"], "enum": ["a", "b", None]},
        ),
        ({"type": "string", "nullable": False}, {"type": "string"}),
        (
            {"$ref": "#/components/schemas/B", "nullable": True},
            {"anyOf": [{"$ref": "miles:/contracts/materiel/v2/b"}, {"type": "null"}]},
        ),
        (
            {"type": "number", "minimum": 0, "exclusiveMinimum": True},
            {"type": "number", "exclusiveMinimum": 0},
        ),
        (
            {"type": "number", "maximum": 9, "exclusiveMaximum": False},
            {"type": "number", "maximum": 9},
        ),
        ({"type": "string", "example": "x"}, {"type": "string", "examples": ["x"]}),
    ],
    ids=[
        "nullable",
        "nullable-enum",
        "not-nullable",
        "nullable-ref",
        "exclusive",
        "inclusive",
        "example",
    ],
)
def test_openapi_30_keywords_become_json_schema_2020_12(
    given: dict[str, Any], expected: dict[str, Any]
) -> None:
    models = _derived(
        {"A": {"type": "object", "properties": {"v": given}}, "B": {"type": "object"}}
    )

    assert models["a"]["properties"]["v"] == expected


def test_a_property_named_like_a_keyword_is_a_name_not_a_keyword() -> None:
    models = _derived(
        {"A": {"type": "object", "properties": {"example": {"type": "string"}, "nullable": {}}}}
    )

    assert set(models["a"]["properties"]) == {"example", "nullable"}


def test_an_openapi_31_schema_is_kept_as_is_apart_from_its_refs() -> None:
    schema = {"type": ["string", "null"], "exclusiveMinimum": 3, "example": "kept"}

    models = _derived({"A": schema}, openapi="3.1.0")

    assert {k: v for k, v in models["a"].items() if k not in ("$schema", "$id", "title")} == schema


def test_a_non_object_schema_is_still_a_model() -> None:
    # Un contrat déclare aussi des énumérations : elles sont des schémas comme les autres.
    models = _derived({"Status": {"type": "string", "enum": ["open", "closed"]}})

    assert models["status"]["enum"] == ["open", "closed"]


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ("PickupPoint", "pickup-point"),
        ("pickup_point", "pickup_point"),
        ("Point.v2", "point-v2"),
        ("A", "a"),
    ],
)
def test_schema_names_are_normalized(source: str, name: str) -> None:
    assert model_name(source) == name


def test_every_refusal_is_named_and_nothing_is_derived() -> None:
    codes = _codes(
        {
            "Point": {"type": "object"},
            "point": {"type": "object"},
            "@@": {"type": "object"},
            "Ref": {"type": "object", "properties": {"p": {"$ref": "#/components/parameters/x"}}},
            "Lost": {
                "type": "object",
                "properties": {"p": {"$ref": "#/components/schemas/Nowhere"}},
            },
            "Bound": {"type": "number", "exclusiveMinimum": True},
            "Bad": {"type": "texte"},
        }
    )

    assert sorted(codes) == sorted(
        [
            ("components.schemas.@@", "nom_de_schema_inconvertible"),
            ("components.schemas.point", "noms_de_schema_en_collision"),
            ("components.schemas.Ref.properties.p.$ref", "reference_non_convertible"),
            ("components.schemas.Lost.properties.p.$ref", "reference_non_convertible"),
            ("components.schemas.Bound.exclusiveMinimum", "borne_exclusive_sans_borne"),
            ("components.schemas.Bad", "schema_invalide"),
        ]
    )


def _nested(depth: int) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "string"}
    for _ in range(depth):
        node = {"type": "array", "items": node}
    return node


def test_nesting_is_followed_up_to_the_bound_then_refused_without_exhausting_the_stack() -> None:
    assert _derived({"Flat": _nested(0)})["flat"]["type"] == "string"
    assert _derived({"One": _nested(1)})["one"]["items"] == {"type": "string"}
    assert _derived({"Max": _nested(MAX_DEPTH)})["max"]["type"] == "array"

    assert _codes({"Deep": _nested(MAX_DEPTH + 5)}) == [
        ("components.schemas.Deep" + ".items" * (MAX_DEPTH + 1), "schema_trop_profond")
    ]
