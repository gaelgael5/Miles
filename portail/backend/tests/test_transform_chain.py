from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from miles.transform.api_transform import chains_router
from miles.transform.chain import (
    ChainFailedError,
    ChainInvalidError,
    StepSpec,
    compile_chain,
    run_chain,
)

BUDGET = 10_000
MESSAGE = {"colis": {"ref": "C-42", "poids": "1.5"}, "client": "Gaël"}


def _final(steps: list[StepSpec], message: Any = MESSAGE) -> Any:
    return run_chain(compile_chain(steps), message, BUDGET)[-1]


def test_steps_apply_in_order_each_on_the_message_of_the_previous() -> None:
    steps = [
        StepSpec('{ "ref": $.colis.ref, "poids": $.colis.poids#decimal }'),
        StepSpec('{ "reference": $.ref, "kg": $.poids }'),
    ]

    trace = run_chain(compile_chain(steps), MESSAGE, BUDGET)

    assert trace == [{"ref": "C-42", "poids": 1.5}, {"reference": "C-42", "kg": 1.5}]


def test_projection_keeps_the_message_and_creates_the_missing_path() -> None:
    step = StepSpec('{ "kg": $.colis.poids#decimal }', target="$.calcul.poids")

    result = _final([step])

    assert result == MESSAGE | {"calcul": {"poids": {"kg": 1.5}}}
    # Le message reçu n'est pas modifié en place : chaque étape travaille sur une copie.
    assert "calcul" not in MESSAGE


def test_projection_can_replace_an_existing_value_or_an_array_item() -> None:
    message = {"lignes": [{"q": 1}, {"q": 2}], "statut": "brut"}

    result = _final(
        [StepSpec('"traite"', target="$.statut"), StepSpec('{ "q": 9 }', target="$.lignes[1]")],
        message,
    )

    assert result == {"lignes": [{"q": 1}, {"q": 9}], "statut": "traite"}


def test_without_a_message_the_first_step_receives_an_empty_object() -> None:
    assert _final([StepSpec('{ "source": $.x ?? "aucune" }')], None) == {"source": "aucune"}


def test_an_empty_chain_returns_the_message_unchanged() -> None:
    assert run_chain(compile_chain([]), MESSAGE, BUDGET) == [MESSAGE]


@pytest.mark.parametrize(
    "target",
    ["$.lignes[*]", "$.lignes[?(@.q == 1)]", "$..q", "$.lignes[0:2]", "$", "pas un chemin", "@.x"],
)
def test_a_target_that_is_not_a_single_place_is_refused_when_written(target: str) -> None:
    with pytest.raises(ChainInvalidError) as caught:
        compile_chain([StepSpec('{ "a": 1 }'), StepSpec('{ "a": 1 }', target=target)])

    [problem] = caught.value.problems
    assert (problem.step, problem.code) == (1, "cible_invalide")


def test_every_faulty_step_is_reported_with_its_rank() -> None:
    steps = [
        StepSpec('{ "a": $.x + 1 }'),
        StepSpec('{ "b": $.y }'),
        StepSpec('{ "c": '),
        StepSpec('{ "d": 1 }', target="$.l[*]"),
    ]

    with pytest.raises(ChainInvalidError) as caught:
        compile_chain(steps)

    assert [(p.step, p.code) for p in caught.value.problems] == [
        (0, "hors_profil"),
        (2, "syntaxe"),
        (3, "cible_invalide"),
    ]


@pytest.mark.parametrize(
    ("message", "target", "expected"),
    [
        ({"statut": "brut"}, "$.statut.detail", {"statut": {"detail": {"a": 1}}}),
        ({"statut": None}, "$.statut.detail", {"statut": {"detail": {"a": 1}}}),
        ("texte", "$.a", {"a": {"a": 1}}),
    ],
    ids=["texte", "null", "racine"],
)
def test_a_value_crossed_by_the_target_is_overwritten_by_an_object(
    message: Any, target: str, expected: Any
) -> None:
    # Décision de Gael (22/10/2026) : la valeur traversée est écrasée.
    assert _final([StepSpec('{ "a": 1 }', target=target)], message) == expected


def test_a_missing_array_item_is_not_created() -> None:
    with pytest.raises(ChainFailedError) as caught:
        _final([StepSpec('{ "a": 1 }', target="$.lignes[3]")], {"lignes": [1]})

    assert (caught.value.step, caught.value.cause.code) == (0, "cible_impossible")


def test_a_failing_step_fails_the_whole_chain_and_names_its_rank() -> None:
    steps = [StepSpec('{ "poids": $.colis.ref }'), StepSpec('{ "kg": $.poids#decimal }')]

    with pytest.raises(ChainFailedError) as caught:
        run_chain(compile_chain(steps), MESSAGE, BUDGET)

    assert (caught.value.step, caught.value.cause.code, caught.value.cause.path) == (
        1,
        "conversion",
        "$.poids",
    )


def test_check_route_shows_the_message_after_each_step_or_where_it_fails() -> None:
    app = FastAPI()
    app.include_router(chains_router)
    app.state.transform_budget = BUDGET
    client = TestClient(app)
    steps = [{"template": '{ "ref": $.colis.ref }'}, {"template": '"ok"', "target": "$.statut"}]

    passed = client.post("/api/transformations/check", json={"steps": steps, "sample": MESSAGE})
    failed = client.post(
        "/api/transformations/check",
        json={"steps": [{"template": '{ "k": $.colis.ref#integer }'}], "sample": MESSAGE},
    )

    assert passed.json()["trace"] == [{"ref": "C-42"}, {"ref": "C-42", "statut": "ok"}]
    assert failed.json()["failure"] == {
        "step": 0,
        "evaluation": {
            "code": "conversion",
            "message": None,
            "path": "$.colis.ref",
            "expected": "integer",
        },
    }


def test_an_unimplemented_filter_operator_is_a_named_refusal_carried_to_the_screen() -> None:
    """Le code est DISTINCT de `syntaxe` : le texte n'a rien de fautif, c'est le moteur
    qui ne sait pas encore le faire. Dire « illisible » enverrait l'utilisateur chercher
    une faute de frappe qui n'existe pas.

    Avant cette reprise, `NotImplementedError` traversait Miles jusqu'à un 500 et la
    personne lisait « voir les journaux du back-office » (mesuré sur test1, 31/10/2026).
    """
    with pytest.raises(ChainInvalidError) as caught:
        compile_chain([StepSpec('{ "a": $.liste[?(@.k nin [1, 2])] }', None)])

    problem = caught.value.problems[0]
    assert problem.code == "non_supporte"
    assert "nin" in (problem.detail or "")
