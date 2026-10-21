from __future__ import annotations

import json

import pytest

from miles.contracts.openapi import (
    ContractInvalidError,
    ContractSyntaxError,
    UnsupportedVersionError,
    parse_contract,
    propose_slug,
)

SUIVI = """openapi: 3.0.3
info:
  title: Suivi des demandes
  version: "1.2"
paths:
  /demandes/{id}:
    get:
      operationId: lireDemande
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Demande"}
components:
  schemas:
    Demande: {type: object}
"""


def test_valid_contract_gives_its_title_and_operations() -> None:
    parsed = parse_contract(SUIVI)

    assert (parsed.title, parsed.openapi) == ("Suivi des demandes", "3.0.3")
    assert [(o.method, o.path, o.operation_id) for o in parsed.operations] == [
        ("get", "/demandes/{id}", "lireDemande")
    ]


def test_json_contract_is_read_like_yaml() -> None:
    doc = {"openapi": "3.1.0", "info": {"title": "Matériel", "version": "1"}, "paths": {}}

    assert parse_contract(json.dumps(doc)).operations == ()


def test_webhooks_of_an_inbound_contract_are_operations() -> None:
    doc = (
        'openapi: 3.1.0\ninfo: {title: Evenements, version: "1"}\nwebhooks:\n'
        '  colisRecu:\n    post:\n      responses:\n        "200": {description: ok}\n'
    )

    assert [(o.method, o.path) for o in parse_contract(doc).operations] == [("post", "colisRecu")]


def test_unreadable_file_gives_the_position() -> None:
    with pytest.raises(ContractSyntaxError) as caught:
        parse_contract("openapi: 3.0.3\ninfo: [\n")

    assert caught.value.line is not None and caught.value.column is not None


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("swagger: '2.0'\ninfo: {title: x}\n", "2.0"),
        ("openapi: 3.2.0\n", "3.2.0"),
        ("a: 1\n", None),
    ],
    ids=["swagger-2", "3.2", "absente"],
)
def test_unsupported_version_is_named(text: str, found: str | None) -> None:
    with pytest.raises(UnsupportedVersionError) as caught:
        parse_contract(text)

    assert caught.value.found == found


def test_spec_violations_are_listed_with_their_path() -> None:
    with pytest.raises(ContractInvalidError) as caught:
        parse_contract("openapi: 3.1.0\ninfo: {title: x}\npaths: {}\n")

    assert [(p.path, p.message) for p in caught.value.problems] == [
        ("$.info", "'version' is a required property")
    ]


def test_external_reference_is_refused_before_anything_is_fetched() -> None:
    doc = SUIVI.replace('"#/components/schemas/Demande"', '"http://169.254.169.254/x.yaml"')

    with pytest.raises(ContractInvalidError) as caught:
        parse_contract(doc)

    [problem] = caught.value.problems
    assert problem.message == "référence externe refusée : http://169.254.169.254/x.yaml"
    assert problem.path.endswith(".schema")


def test_dangling_internal_reference_is_reported_not_raised() -> None:
    doc = SUIVI.replace("#/components/schemas/Demande", "#/components/schemas/Absente")

    with pytest.raises(ContractInvalidError) as caught:
        parse_contract(doc)

    assert caught.value.problems[0].message == (
        "référence introuvable : #/components/schemas/Absente"
    )


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Suivi des demandes", "suivi-des-demandes"),
        ("  API Matériel — v2 ", "api-materiel-v2"),
        ("Événements_Colis", "evenements-colis"),
        ("这是", ""),
        ("x" * 80, "x" * 63),
    ],
)
def test_slug_is_proposed_from_the_title(title: str, slug: str) -> None:
    assert propose_slug(title) == slug
