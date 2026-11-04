from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.gate import auth_gate
from miles_socle.auth.passwords import hash_password
from miles_socle.auth.throttle import LoginThrottle

SIGNE = "/api/peer/ping"
ORDINAIRE = "/api/quelque-chose"


class _NoSessionDb:
    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def _app(tmp_path: Path, *, signes: frozenset[str] | None, avec_admin: bool = True) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_gate)
    routeur = APIRouter()

    @routeur.post(SIGNE)
    async def peer_ping() -> dict[str, str]:
        # Tient la place de la vraie route de pair, qui vérifie ELLE-MÊME la signature.
        return {"atteinte": "signee"}

    @routeur.get(ORDINAIRE)
    async def ordinaire() -> dict[str, str]:
        return {"atteinte": "ordinaire"}

    app.include_router(routeur)
    account = (
        AdminAccount(
            email="admin@essai.invalid",
            username="admin",
            password_hash=SecretStr(hash_password("mot-de-passe-d-essai-suffisant")),
        )
        if avec_admin
        else None
    )
    app.state.auth = AuthContext(
        store=AdminAccountStore(tmp_path / ".env", tmp_path / ".env.bak", account),
        db=_NoSessionDb(),
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=1),
        cookie_secure=True,
    )
    if signes is not None:
        app.state.signed_api_paths = signes
    return app


def test_sans_declaration_aucune_route_ne_passe_sans_session(tmp_path: Path) -> None:
    # Le défaut est l'ensemble VIDE : le portail et le module d'enrôlement ne déclarent
    # rien, et rien ne doit s'ouvrir chez eux parce que ce passage existe.
    client = TestClient(_app(tmp_path, signes=None))

    assert client.post(SIGNE).status_code == 401
    assert client.get(ORDINAIRE).status_code == 401


def test_une_declaration_vide_n_ouvre_rien(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, signes=frozenset()))

    assert client.post(SIGNE).status_code == 401


def test_un_chemin_declare_est_remis_a_la_route_qui_verifie_la_signature(
    tmp_path: Path,
) -> None:
    client = TestClient(_app(tmp_path, signes=frozenset({SIGNE})))

    reponse = client.post(SIGNE)

    assert reponse.status_code == 200
    assert reponse.json() == {"atteinte": "signee"}


def test_declarer_un_chemin_n_ouvre_pas_les_autres(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, signes=frozenset({SIGNE})))

    assert client.get(ORDINAIRE).status_code == 401


def test_un_chemin_declare_passe_meme_avant_l_amorcage(tmp_path: Path) -> None:
    # Un appel de pair ne dépend pas de l'existence d'un administrateur humain : sa clé
    # n'est connue que par appariement, et c'est elle qui l'autorise.
    client = TestClient(_app(tmp_path, signes=frozenset({SIGNE}), avec_admin=False))

    assert client.post(SIGNE).status_code == 200
    # L'amorçage reste exigé partout ailleurs.
    assert client.get(ORDINAIRE).status_code == 403


@pytest.mark.parametrize("chemin", ["/api/peer", "/api/peer/ping/plus", "/api/peer/ping2"])
def test_le_passage_est_un_chemin_exact_jamais_un_prefixe(tmp_path: Path, chemin: str) -> None:
    # Un préfixe ouvrirait des routes que personne n'a déclarées : la correspondance est
    # exacte, comme pour la liste blanche publique.
    app = _app(tmp_path, signes=frozenset({SIGNE}))

    @app.get(chemin)
    async def voisine() -> dict[str, str]:
        return {"atteinte": "voisine"}

    assert TestClient(app).get(chemin).status_code == 401
