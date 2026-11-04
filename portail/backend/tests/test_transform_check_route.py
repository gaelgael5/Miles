"""La route qui éprouve un template pour l'écran : ce que l'auteur voit en écrivant.

Le MOTEUR est au socle depuis le 03/11/2026 (enabler `b2a215ee`) et sa suite l'a suivi ;
ce qui reste ici est la route, qui est une surface du portail. Elle est testée à part
parce qu'elle promet autre chose que le moteur : un verdict STABLE et complet pour une
saisie en cours, là où le moteur ne promet qu'un résultat ou un refus.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from miles.transform.api_transform import router

BUDGET = 10_000


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
