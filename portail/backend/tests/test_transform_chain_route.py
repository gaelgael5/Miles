"""La route qui montre le message après chaque étape d'une chaîne, pour l'écran.

L'APPLICATION d'une chaîne est au socle depuis le 03/11/2026 (enabler `b2a215ee`), parce
que le module d'environnement l'exécute aussi. Ce qui reste ici est la route : elle sert
une saisie en cours, et doit montrer OÙ une chaîne échoue — ce que l'exécution, elle, n'a
pas à faire, puisqu'elle refuse le lot.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from miles.transform.api_transform import chains_router

BUDGET = 10_000
# Le jeu d'essai est recopié de la suite du moteur, et non importé : un harnais partagé
# entre deux racines est précisément ce que le test de frontière interdit.
MESSAGE = {"colis": {"ref": "C-42", "poids": "1.5"}, "client": "Gaël"}


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
