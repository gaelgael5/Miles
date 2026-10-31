from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_json import FunctionRegistry, default_registry

from miles.transform import engine
from miles.transform.api_transform import router
from miles.transform.engine import (
    EvaluationError,
    OutsideProfileError,
    TemplateSyntaxError,
    UnsupportedConstructError,
    compile_template,
    evaluate,
)

BUDGET = 10_000


def _run(source: str, document: Any, budget: int = BUDGET) -> Any:
    return evaluate(compile_template(source), document, budget)


def test_template_within_profile_is_accepted_and_evaluated() -> None:
    source = (
        '{ "destinataire": $.addresses[?(@.kind == "RECIPIENT")].name,'
        ' "poids": $.weight#decimal, "ref": $.ref ?? "sans-ref",'
        ' "lignes": [ { "$source": $.lines, "$where": $.qty > 0, "code": $.code } ] }'
    )
    document = {
        "addresses": [{"kind": "SENDER", "name": "A"}, {"kind": "RECIPIENT", "name": "B"}],
        "weight": "1.5",
        "lines": [{"code": "x", "qty": 2}, {"code": "y", "qty": 0}],
    }

    assert _run(source, document) == {
        "destinataire": "B",
        "poids": 1.5,
        "ref": "sans-ref",
        "lignes": [{"code": "x"}],
    }


def test_unreadable_template_gives_its_position() -> None:
    with pytest.raises(TemplateSyntaxError) as caught:
        compile_template('{ "a": $.x,\n  "b": }')

    assert (caught.value.line, caught.value.column) == (2, 7)


def test_a_grammatical_but_unimplemented_filter_operator_is_a_refusal_not_a_crash() -> None:
    """`nin`, `contains`, `size` et `empty` sont ANNONCÉS par la grammaire du moteur —
    son propre message d'erreur les liste comme attendus — mais le constructeur d'AST
    lève `NotImplementedError` dessus. Sans cette reprise, l'exception traversait Miles
    jusqu'à un 500, et la personne lisait « voir les journaux du back-office » pour une
    construction qu'elle venait de taper (mesuré sur test1 le 31/10/2026).
    """
    with pytest.raises(UnsupportedConstructError) as caught:
        compile_template('{ "a": $.liste[?(@.k nin [1, 2])] }')

    assert "nin" in caught.value.message


def test_every_construct_outside_the_profile_is_named_and_located() -> None:
    source = '{ "a": $.x + 1,\n  "b": when($.k) { "A": 1 },\n  "v:": 3,\n  "c": !$.flag }'

    with pytest.raises(OutsideProfileError) as caught:
        compile_template(source)

    found = {(v.construct, v.detail, v.line) for v in caught.value.violations}
    assert found == {
        ("operateur", "add", 1),
        ("when", None, 2),
        ("variable", "v", 3),
        ("operateur", "not", 4),
    }


@pytest.mark.parametrize(
    ("source", "construct"),
    [
        ('{ "r": $.i[?(@.a == 1 & @.b == 2)] }', "predicat"),
        ('{ "r": $.i[?(@.a == $.b)] }', "predicat_non_clos"),
        ('{ "l": [ { "$source": $.i, "$where": $.a == 1 | $.b == 2, "x": $.x } ] }', "predicat"),
        (
            '{ "l": [ { "$source": $.i, "$where": $.a == concat("x"), "x": $.x } ] }',
            "predicat_non_clos",
        ),
    ],
    ids=["deux-predicats", "filtre-non-clos", "where-deux-predicats", "where-non-clos"],
)
def test_select_or_where_needs_a_single_closed_predicate(source: str, construct: str) -> None:
    with pytest.raises(OutsideProfileError) as caught:
        compile_template(source)

    assert [v.construct for v in caught.value.violations] == [construct]


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({}, "repli"),
        ({"v": None}, "repli"),
        ({"v": ""}, ""),
        ({"v": []}, []),
        ({"v": 0}, 0),
        ({"v": False}, False),
    ],
    ids=["absent", "null", "chaine-vide", "tableau-vide", "zero", "faux"],
)
def test_coalesce_skips_only_absent_and_null(document: dict[str, Any], expected: Any) -> None:
    # Décision de Gael (22/10/2026) : zéro, faux, chaîne et tableau vides sont des valeurs.
    template = compile_template('{ "r": $.v ?? "repli" }')

    assert evaluate(template, document | {"autre": 1}, BUDGET) == {"r": expected}


@pytest.mark.parametrize(
    ("value", "cast", "result"),
    [
        ("12", "integer", 12),
        (3.0, "integer", 3),
        ("1.5", "decimal", 1.5),
        ("true", "boolean", True),
        (12, "string", "12"),
        ("2026-10-22T08:00:00", "datetime", "2026-10-22T08:00:00"),
        ("https://x.test/a", "uri", "https://x.test/a"),
    ],
)
def test_compatible_value_is_converted(value: Any, cast: str, result: Any) -> None:
    assert _run(f'{{ "r": $.v#{cast} }}', {"v": value}) == {"r": result}


@pytest.mark.parametrize(
    ("value", "cast"),
    [
        ("douze", "integer"),
        (1.5, "integer"),
        (True, "integer"),
        ("oui", "boolean"),
        ({"a": 1}, "string"),
        ("demain", "datetime"),
        ("pas-un-uuid", "uuid"),
        ("colis/42", "uri"),
    ],
)
def test_incompatible_value_names_the_path_and_the_type(value: Any, cast: str) -> None:
    with pytest.raises(EvaluationError) as caught:
        _run(f'{{ "r": $.v#{cast} }}', {"v": value})

    assert (caught.value.code, caught.value.path, caught.value.expected) == (
        "conversion",
        "$.v",
        cast,
    )


def test_absent_value_stays_absent_through_a_cast_instead_of_a_default() -> None:
    # Le convert du moteur rendrait 0 : un poids manquant deviendrait un poids nul.
    assert _run('{ "r": $.v#integer, "s": $.v#integer ?? -1 }', {"x": 1}) == {"r": None, "s": -1}


@pytest.mark.parametrize("document", [None, {}], ids=["absente", "objet-vide"])
def test_without_a_message_the_source_is_an_empty_object(document: Any) -> None:
    # Gael, 22/10/2026 : pas de message, la source vaut {} ; un template de constantes
    # produit alors un message à partir de rien.
    assert _run('{ "a": 1, "b": $.x ?? "repli" }', document) == {"a": 1, "b": "repli"}


def test_evaluation_beyond_the_configured_budget_is_interrupted() -> None:
    source = '{ "l": [ { "$source": $.items, "n": $.n } ] }'
    document = {"items": [{"n": i} for i in range(1_000)]}

    assert len(_run(source, document, budget=100_000)["l"]) == 1_000
    with pytest.raises(EvaluationError) as caught:
        _run(source, document, budget=500)
    assert (caught.value.code, caught.value.expected) == ("budget_depasse", "500")


def test_only_core_functions_of_the_engine_enter_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def from_plugin(ctx: Any, url: Any = None) -> Any:
        """Appel HTTP d'un plugin installé."""

    from_plugin.__module__ = "urban_json_http.functions"
    installed = FunctionRegistry()
    installed.register("upper", default_registry.get("upper"), (), "Majuscules.")
    installed.register("http_get", from_plugin, (), "Appel HTTP.")
    installed.register("convert", default_registry.get("convert"), (), "Conversion du moteur.")
    monkeypatch.setattr(engine, "default_registry", installed)

    registry = engine._registry()

    assert sorted(registry.names()) == ["convert", "upper"]
    # La conversion est celle de Miles, stricte, pas celle du moteur.
    assert registry.get("convert") is engine._strict_convert


def test_a_function_missing_from_the_catalogue_is_refused_when_written() -> None:
    with pytest.raises(OutsideProfileError) as caught:
        compile_template('{ "a": upper($.x), "b": http_get($.url) }')

    assert [(v.construct, v.detail) for v in caught.value.violations] == [
        ("fonction_inconnue", "http_get")
    ]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.transform_budget = BUDGET
    return TestClient(app)


def test_check_route_gives_the_same_verdict_each_time() -> None:
    client = _client()
    body = {"template": '{ "a": $.x + 1, "b": $.y }', "sample": {"x": 1}}

    first, second = (
        client.post("/api/templates/check", json=body),
        client.post("/api/templates/check", json=body),
    )

    assert first.json() == second.json()
    assert first.json()["valid"] is False
    assert first.json()["violations"] == [
        {"construction": "operateur", "detail": "add", "line": 1, "column": 7}
    ]


def test_check_route_without_sample_does_not_claim_the_result_conforms() -> None:
    client = _client()

    unsampled = client.post("/api/templates/check", json={"template": '{ "a": $.x }'})
    sampled = client.post(
        "/api/templates/check", json={"template": '{ "a": $.x#integer }', "sample": {"x": "z"}}
    )
    unreadable = client.post("/api/templates/check", json={"template": '{ "a": '})

    assert unsampled.json()["valid"] is True and unsampled.json()["evaluated"] is False
    assert sampled.json()["evaluation"] == {
        "code": "conversion",
        "message": None,
        "path": "$.x",
        "expected": "integer",
    }
    assert unreadable.json()["syntax"]["line"] == 1
