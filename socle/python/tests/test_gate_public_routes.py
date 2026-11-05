from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.gate import auth_gate
from miles_socle.auth.passwords import hash_password
from miles_socle.auth.throttle import LoginThrottle

# Un contrat se pointe par une URL qu'un intégrateur ouvre sans compte (Gael, 05/11/2026).
CONTRAT = "/api/ingestion/contract/{source}"
ORDINAIRE = "/api/quelque-chose"


class _NoSessionDb:
    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def _app(tmp_path: Path, *, ouvertes: frozenset[tuple[str, str]] | None) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_gate)
    routeur = APIRouter()

    @routeur.get(CONTRAT)
    async def contrat(source: str) -> dict[str, str]:
        return {"source": source}

    @routeur.put(CONTRAT)
    async def ecrire(source: str) -> dict[str, str]:
        # Même chemin, autre méthode : elle ne doit PAS s'ouvrir avec la lecture.
        return {"ecrit": source}

    @routeur.get(ORDINAIRE)
    async def ordinaire() -> dict[str, str]:
        return {"atteinte": "ordinaire"}

    app.include_router(routeur)
    app.state.auth = AuthContext(
        store=AdminAccountStore(
            tmp_path / ".env",
            tmp_path / ".env.bak",
            AdminAccount(
                email="admin@essai.invalid",
                username="admin",
                password_hash=SecretStr(hash_password("mot-de-passe-d-essai-suffisant")),
            ),
        ),
        db=_NoSessionDb(),
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=1),
        cookie_secure=True,
    )
    if ouvertes is not None:
        app.state.public_api_routes = ouvertes
    return app


def test_sans_declaration_rien_ne_s_ouvre(tmp_path: Path) -> None:
    # Le défaut est l'ensemble VIDE : un produit qui ne déclare rien n'ouvre rien parce
    # que ce passage existe.
    client = TestClient(_app(tmp_path, ouvertes=None))

    assert client.get("/api/ingestion/contract/sites").status_code == 401


def test_une_route_declaree_s_ouvre_a_qui_n_a_pas_de_session(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, ouvertes=frozenset({("GET", CONTRAT)})))

    reponse = client.get("/api/ingestion/contract/sites")

    assert reponse.status_code == 200
    assert reponse.json() == {"source": "sites"}


def test_ouvrir_la_lecture_n_ouvre_pas_l_ecriture(tmp_path: Path) -> None:
    # La méthode entre dans la correspondance : un contrat se LIT sans compte, il ne
    # s'écrit pas.
    client = TestClient(_app(tmp_path, ouvertes=frozenset({("GET", CONTRAT)})))

    assert client.put("/api/ingestion/contract/sites").status_code == 401


def test_declarer_une_route_n_ouvre_pas_ses_voisines(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, ouvertes=frozenset({("GET", CONTRAT)})))

    assert client.get(ORDINAIRE).status_code == 401


def test_le_gabarit_declare_n_ouvre_pas_ce_qu_on_monterait_dessous(tmp_path: Path) -> None:
    # La correspondance se fait par ROUTAGE, pas par préfixe : une route ajoutée demain
    # sous la même racine reste fermée, sans que son auteur ait à y penser.
    app = _app(tmp_path, ouvertes=frozenset({("GET", CONTRAT)}))

    @app.get("/api/ingestion/contract/{source}/secrets")
    async def dessous(source: str) -> dict[str, str]:
        return {"source": source}

    assert TestClient(app).get("/api/ingestion/contract/sites/secrets").status_code == 401
