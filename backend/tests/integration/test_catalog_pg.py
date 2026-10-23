from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.test_datamodels_pg import PERSONNE
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/catalog"
MODELS = "/api/workspaces/retrait/data-models"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _head(forge: Forge) -> str:
    got = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches/work/edition")
    return str(got.json()["commit"]["id"])


async def test_catalogue_follows_the_branch_and_answers_for_a_past_commit(forge: Forge) -> None:
    fresh = await forge.client.get(ROUTE, timeout=120)
    before = await _head(forge)
    await forge.client.post(MODELS, json={"scope": "shared", "content": PERSONNE}, timeout=120)

    now = await forge.client.get(ROUTE, timeout=120)
    then = await forge.client.get(ROUTE, params={"commit": before}, timeout=120)

    # Branche fraîchement initialisée : pas de modèle, toutes les fonctions.
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["models"] == []
    assert {"convert", "concat"} <= {f["name"] for f in fresh.json()["functions"]}
    assert [m["name"] for m in now.json()["models"]] == ["personne"]
    assert now.json()["models"][0]["properties"] == [{"name": "nom", "type": "chaine"}]
    # La personne qui a la main lit sa tête locale ; publiée, c'est celle de la forge.
    await forge.publish()
    assert now.json()["commit"] == await _head(forge)
    # À un commit passé : ce qui était disponible alors, pas l'état courant.
    assert (then.json()["commit"], then.json()["models"]) == (before, [])
    assert now.json()["app_floor"] is None


async def test_unknown_commit_or_branch_is_refused(forge: Forge) -> None:
    unknown = await forge.client.get(ROUTE, params={"commit": "0" * 40}, timeout=120)
    short = await forge.client.get(ROUTE, params={"commit": "abc123"}, timeout=120)
    branch = await forge.client.get(ROUTE, params={"branch": "inconnue"}, timeout=120)

    assert (unknown.status_code, unknown.json()["detail"]) == (404, "commit_inconnu")
    assert short.json()["detail"] == "commit_inconnu"
    assert (branch.status_code, branch.json()["detail"]) == (404, "branche_inconnue")
