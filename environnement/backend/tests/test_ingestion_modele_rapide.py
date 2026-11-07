"""Le chemin rapide du contrôle de modèle : il n'accepte que ce que l'autorité accepte.

**C'est ce fichier qui TIENT la liste `AGREED`**, et non la main de celui qui l'a écrite :
chaque mot-clé y a son cas, le test exige que la liste et les cas se recouvrent exactement,
et il compare les deux validateurs sur chacun. Une montée de version du validateur compilé
qui ferait diverger un mot-clé rougit ici, au lieu de laisser entrer en silence des objets
que le modèle refuse — « le modèle en base doit être valide » est une contrainte non
négociable (Gael, 07/11/2026).

Les mots-clés qui DIVERGENT ont leurs cas aussi, et c'est tout aussi important : ils
prouvent que l'énumération les écarte, et que ce qui doit être refusé l'est toujours.
"""

from __future__ import annotations

import json
from typing import Any

import fastjsonschema
import pytest
from jsonschema import Draft202012Validator

from environnement.ingestion.conformance import (
    AGREED,
    DIALECT,
    ModelViolation,
    _compiled,
    _keywords,
    check_conformance,
    model_validator,
)

# Un cas par mot-clé de `AGREED` : le schéma qui ne l'éprouve QUE lui, et des instances
# dont le verdict doit DIFFÉRER entre elles — un jeu d'essai que tout fait passer ne
# prouve rien. Les mots-clés auxiliaires d'un cas (`contains` sous `maxContains`) sont
# admis : seul compte que le mot-clé visé soit éprouvé.
ACCORD: dict[str, tuple[Any, list[Any]]] = {
    "type": ({"type": "string"}, ["a", 1, None, [], {}]),
    "enum": ({"enum": ["a", 1, None]}, ["a", 1, None, "b", 2]),
    "const": ({"const": "a"}, ["a", "b", 1]),
    "multipleOf": ({"multipleOf": 3}, [9, 10, 9.0, 1.5]),
    "maximum": ({"maximum": 5}, [5, 6, 4.9, "a"]),
    "exclusiveMaximum": ({"exclusiveMaximum": 5}, [4, 5, 6]),
    "minimum": ({"minimum": 5}, [5, 4, 6]),
    "exclusiveMinimum": ({"exclusiveMinimum": 5}, [6, 5, 4]),
    "maxLength": ({"maxLength": 2}, ["ab", "abc", "é", "éé", "ééé"]),
    "minLength": ({"minLength": 2}, ["ab", "a", ""]),
    "pattern": ({"pattern": "^FR-[0-9]+$"}, ["FR-1", "FR-", "DE-1", 1]),
    "items": ({"items": {"type": "integer"}}, [[1, 2], [1, "a"], []]),
    "maxItems": ({"maxItems": 2}, [[1, 2], [1, 2, 3], []]),
    "minItems": ({"minItems": 2}, [[1, 2], [1], []]),
    "uniqueItems": ({"uniqueItems": True}, [[1, 2], [1, 1], [{"a": 1}, {"a": 1}], []]),
    "contains": ({"contains": {"type": "integer"}}, [[1, "a"], ["a"], []]),
    "properties": ({"properties": {"a": {"type": "integer"}}}, [{"a": 1}, {"a": "x"}, {}]),
    "patternProperties": (
        {"patternProperties": {"^a": {"type": "integer"}}},
        [{"ab": 1}, {"ab": "x"}, {"b": "x"}],
    ),
    "additionalProperties": (
        {"properties": {"a": {}}, "additionalProperties": False},
        [{"a": 1}, {"a": 1, "b": 2}, {}],
    ),
    "required": ({"required": ["a", "b"]}, [{"a": 1, "b": 2}, {"a": 1}, {}]),
    "maxProperties": ({"maxProperties": 1}, [{"a": 1}, {"a": 1, "b": 2}, {}]),
    "minProperties": ({"minProperties": 2}, [{"a": 1, "b": 2}, {"a": 1}, {}]),
    "propertyNames": ({"propertyNames": {"pattern": "^a"}}, [{"ab": 1}, {"b": 1}, {}]),
    "allOf": ({"allOf": [{"type": "object"}, {"required": ["a"]}]}, [{"a": 1}, {}, "x"]),
    "anyOf": ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, ["a", 1, None, 1.5]),
    "oneOf": ({"oneOf": [{"type": "integer"}, {"maximum": 3}]}, [5, 1, "a"]),
    "not": ({"not": {"type": "string"}}, [1, "a", None]),
    "if": ({"if": {"type": "integer"}, "then": {"maximum": 3}}, [1, 5, "a"]),
    "then": ({"if": {"type": "integer"}, "then": {"maximum": 3}}, [1, 5, "a"]),
    "else": (
        {"if": {"type": "integer"}, "then": {"maximum": 3}, "else": {"type": "string"}},
        [1, 5, "a", None],
    ),
    "$ref": (
        {"$defs": {"n": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/n"}}},
        [{"a": 1}, {"a": "x"}, {}],
    ),
    "$defs": (
        {"$defs": {"n": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/n"}}},
        [{"a": 1}, {"a": "x"}, {}],
    ),
    "$schema": ({"$schema": DIALECT, "type": "string"}, ["a", 1]),
    "$id": ({"$id": "miles:/domains/pudo/site", "type": "string"}, ["a", 1]),
    "$comment": ({"$comment": "rien", "type": "string"}, ["a", 1]),
    "title": ({"title": "T", "type": "string"}, ["a", 1]),
    "description": ({"description": "D", "type": "string"}, ["a", 1]),
    "default": ({"default": 1, "type": "string"}, ["a", 1]),
    "examples": ({"examples": [1], "type": "string"}, ["a", 1]),
    "deprecated": ({"deprecated": True, "type": "string"}, ["a", 1]),
    "readOnly": ({"readOnly": True, "type": "string"}, ["a", 1]),
    "writeOnly": ({"writeOnly": True, "type": "string"}, ["a", 1]),
}

# Mesurés DIVERGENTS le 07/11/2026. Chacun porte l'instance qui sépare les deux
# validateurs, et le sens de l'écart : `accepte_a_tort` est le cas dangereux — le compilé
# laisse entrer ce que le modèle refuse.
DESACCORD: dict[str, tuple[Any, Any, bool]] = {
    "prefixItems": (
        {"prefixItems": [{"type": "integer"}, {"type": "string"}]},
        ["a", 1],
        True,
    ),
    "maxContains": ({"contains": {"type": "integer"}, "maxContains": 1}, [1, 2], True),
    "minContains": ({"contains": {"type": "integer"}, "minContains": 2}, [1], True),
    "unevaluatedItems": (
        {"prefixItems": [{"type": "integer"}], "unevaluatedItems": False},
        [1, 2],
        True,
    ),
    "dependentRequired": ({"dependentRequired": {"a": ["b"]}}, {"a": 1}, True),
    "dependentSchemas": ({"dependentSchemas": {"a": {"required": ["b"]}}}, {"a": 1}, True),
    "unevaluatedProperties": (
        {"properties": {"a": {}}, "unevaluatedProperties": False},
        {"a": 1, "b": 2},
        True,
    ),
    "$dynamicRef": (
        {
            "$defs": {"n": {"$dynamicAnchor": "t", "type": "integer"}},
            "properties": {"a": {"$dynamicRef": "#t"}},
        },
        {"a": "x"},
        True,
    ),
    "format": ({"type": "string", "format": "date"}, "pas-une-date", False),
    "contentSchema": (
        {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"type": "object"},
        },
        "pas du json",
        False,
    ),
}


def _authority_accepts(schema: Any, objet: Any) -> bool:
    return next(Draft202012Validator(schema).iter_errors(objet), None) is None


def _fast_accepts(schema: Any, objet: Any) -> bool:
    valide = fastjsonschema.compile(
        schema if isinstance(schema, bool) else {**schema, "$schema": DIALECT}
    )
    try:
        valide(objet)
    except fastjsonschema.JsonSchemaException:
        return False
    return True


def test_the_agreed_list_is_exactly_the_set_of_measured_keywords() -> None:
    """La liste n'est pas tenue à la main : elle est tenue par ce fichier.

    Ajouter un mot-clé à `AGREED` sans lui donner un cas ici fait rougir ce test, et c'est
    exactement ce qu'on veut : un mot-clé non mesuré ne doit pas entrer dans une garde.
    """
    assert AGREED == frozenset(ACCORD)


@pytest.mark.parametrize("keyword", sorted(ACCORD))
def test_an_agreed_keyword_gives_the_same_verdict_on_both_validators(keyword: str) -> None:
    schema, instances = ACCORD[keyword]
    attendus = [_authority_accepts(schema, objet) for objet in instances]

    assert [_fast_accepts(schema, objet) for objet in instances] == attendus, (
        f"{keyword} : les deux validateurs ne disent plus la même chose"
    )
    # Le jeu d'essai doit DISCRIMINER : s'il accepte tout ou refuse tout, l'égalité
    # ci-dessus serait vraie même si les deux validateurs étaient faux.
    assert len(set(attendus)) == 2, f"{keyword} : jeu d'essai non discriminant"


@pytest.mark.parametrize("keyword", sorted(DESACCORD))
def test_a_disagreeing_keyword_is_excluded_from_the_fast_path(keyword: str) -> None:
    """Le mot-clé divergent n'est pas dans la liste, et son schéma n'est pas compilé."""
    schema, _, _ = DESACCORD[keyword]

    assert keyword not in AGREED
    assert _compiled(schema) is None


@pytest.mark.parametrize("keyword", sorted(DESACCORD))
def test_the_measured_divergence_is_still_real(keyword: str) -> None:
    """Le jour où le validateur compilé cessera de diverger, ce test rougira.

    C'est voulu : un mot-clé pourra alors rejoindre `AGREED` après mesure, au lieu d'y
    rester interdit par une peur devenue périmée.
    """
    schema, objet, accepte_a_tort = DESACCORD[keyword]
    autorite = _authority_accepts(schema, objet)

    assert _fast_accepts(schema, objet) != autorite
    assert (not autorite) is accepte_a_tort


@pytest.mark.parametrize("keyword", sorted(DESACCORD))
def test_what_the_model_refuses_is_still_refused_through_the_public_path(keyword: str) -> None:
    """La garde, par la porte réelle : rien ne doit entrer de ce que le modèle refuse.

    C'est LE test de sécurité du dispositif. Sans l'énumération des mots-clés, huit des
    dix cas ci-dessous passeraient — le validateur compilé les accepte.
    """
    schema, objet, accepte_a_tort = DESACCORD[keyword]
    if not accepte_a_tort:
        pytest.skip("ce mot-clé diverge en refusant trop, pas en acceptant trop")

    with pytest.raises(ModelViolation):
        check_conformance(objet, model_validator(schema))


def test_a_rejection_carries_the_message_of_the_authority() -> None:
    """Le chemin rapide ne tranche pas un refus : le compte-rendu garde SON message."""
    schema = {"type": "object", "required": ["Code"], "properties": {"Code": {"type": "string"}}}
    rapide = model_validator(schema)
    assert rapide.fast is not None, "ce schéma doit emprunter le chemin rapide"

    with pytest.raises(ModelViolation) as refus:
        check_conformance({"Code": 42}, rapide)

    attendu = next(Draft202012Validator(schema).iter_errors({"Code": 42}))
    assert refus.value.detail == f"$['Code']: {attendu.message}"


def test_the_real_pudo_model_takes_the_fast_path() -> None:
    """Le modèle réel d'un point relais : si LUI n'était pas éligible, rien ne le serait."""
    schema = {
        "$schema": DIALECT,
        "$id": "miles:/domains/pudo/site",
        "title": "Site",
        "type": "object",
        "required": ["Code", "Libelle"],
        "properties": {
            "Code": {"type": "string"},
            "Libelle": {"type": "string"},
            "Ville": {"type": ["string", "null"]},
            "Latitude": {"type": ["number", "null"]},
        },
    }

    assert model_validator(schema).fast is not None


def test_a_property_named_like_a_keyword_is_not_taken_for_one() -> None:
    """Le piège des tables du socle : dans `properties`, les clés sont des NOMS."""
    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "string"},
            "dependentRequired": {"type": "integer"},
            "unevaluatedProperties": {"type": "boolean"},
        },
    }

    # `items`, `dependentRequired` et `unevaluatedProperties` sont ici des NOMS de
    # propriétés : ils ne doivent pas figurer parmi les mots-clés, sinon ce modèle
    # parfaitement ordinaire serait renvoyé à l'autorité pour rien.
    assert _keywords(schema) == frozenset({"type", "properties"})
    assert model_validator(schema).fast is not None


def test_an_unknown_keyword_sends_the_schema_to_the_authority() -> None:
    """Le défaut est de se méfier : non mesuré n'est pas « sans effet »."""
    assert _compiled({"type": "object", "x-maison": {"regle": 1}}) is None


@pytest.mark.parametrize(
    "schema",
    [
        {"items": [{"type": "integer"}]},
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "string"},
        {"properties": {"a": 12}},
    ],
    ids=["items-en-tableau", "autre-dialecte", "sous-schema-qui-n-est-pas-un-schema"],
)
def test_a_shape_we_cannot_walk_is_not_vouched_for(schema: Any) -> None:
    assert _keywords(schema) is None
    assert _compiled(schema) is None


def test_a_schema_nested_beyond_the_bound_is_not_vouched_for() -> None:
    profond: Any = {"type": "integer"}
    for _ in range(80):
        profond = {"properties": {"n": profond}}

    assert _keywords(profond) is None


def test_a_boolean_schema_has_no_keyword_and_stays_fast() -> None:
    assert _keywords(True) == frozenset()
    assert _compiled(True) is not None
    assert _compiled(False) is not None


def test_both_validators_agree_on_the_whole_real_corpus() -> None:
    """Sur des objets réalistes, et pas seulement sur les cas limites par mot-clé."""
    schema = {
        "type": "object",
        "required": ["Code", "Libelle"],
        "properties": {
            "Code": {"type": "string", "pattern": "^FR-[0-9]+$"},
            "Libelle": {"type": "string", "minLength": 1},
            "Latitude": {"type": ["number", "null"], "minimum": -90, "maximum": 90},
        },
        "additionalProperties": False,
    }
    objets: list[Any] = [
        {"Code": "FR-1", "Libelle": "A", "Latitude": 45.0},
        {"Code": "FR-1", "Libelle": "A", "Latitude": None},
        {"Code": "DE-1", "Libelle": "A"},
        {"Code": "FR-1", "Libelle": ""},
        {"Code": "FR-1", "Libelle": "A", "Latitude": 91},
        {"Code": "FR-1", "Libelle": "A", "trop": 1},
        {"Libelle": "A"},
        "pas un objet",
    ]
    valideur = model_validator(schema)
    assert valideur.fast is not None

    for objet in objets:
        attendu = _authority_accepts(schema, objet)
        try:
            check_conformance(objet, valideur)
            obtenu = True
        except ModelViolation:
            obtenu = False
        assert obtenu is attendu, f"désaccord sur {json.dumps(objet, ensure_ascii=False)}"
