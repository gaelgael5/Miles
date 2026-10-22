from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/transformations"
NORMALISER = '{ "ref": $.colis.ref, "kg": $.colis.poids#decimal }'
ENRICHIR = '{ "pays": $.pays ?? "FR" }'
STEPS = [
    {"name": "normaliser", "template": NORMALISER, "target": None},
    {"name": "enrichir", "template": ENRICHIR, "target": "$.origine"},
]


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _save(forge: Forge, steps: list[dict[str, Any]], label: str = "Import") -> httpx.Response:
    body = {"label": label, "steps": steps}
    return await forge.client.put(f"{ROUTE}/comptes-import", json=body, timeout=120)


async def test_chain_is_written_as_a_directory_with_its_sequence_and_templates(
    forge: Forge,
) -> None:
    saved = await _save(forge, STEPS)
    read = await forge.client.get(f"{ROUTE}/comptes-import", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert saved.status_code == 200, saved.text
    assert read.json() == {"slug": "comptes-import", "label": "Import", "steps": STEPS}
    assert listed.json() == [{"slug": "comptes-import", "label": "Import", "steps": 2}]
    assert await forge.file("transformations/comptes-import/normaliser.jslt") == NORMALISER
    assert await forge.file("transformations/comptes-import/enrichir.jslt") == ENRICHIR
    sequence = await forge.file("transformations/comptes-import/chain.json")
    assert sequence is not None and '"target": "$.origine"' in sequence


async def test_editing_replaces_the_sequence_and_drops_unused_templates(forge: Forge) -> None:
    await _save(forge, STEPS)
    before = await forge.commits()

    replay = await _save(forge, STEPS)
    edited = await _save(forge, [STEPS[1], {**STEPS[0], "name": "nettoyer"}])

    assert replay.headers["x-miles-already-exists"] == "true"
    assert edited.status_code == 200
    assert await forge.commits() == before + 1
    assert await forge.file("transformations/comptes-import/normaliser.jslt") is None
    assert await forge.file("transformations/comptes-import/nettoyer.jslt") == NORMALISER
    read = await forge.client.get(f"{ROUTE}/comptes-import", timeout=120)
    assert [s["name"] for s in read.json()["steps"]] == ["enrichir", "nettoyer"]


async def test_invalid_chain_is_refused_without_writing_and_names_each_step(forge: Forge) -> None:
    before = await forge.commits()

    refused = await _save(
        forge,
        [
            {"name": "a", "template": '{ "x": $.a + 1 }'},
            {"name": "b", "template": '{ "y": 1 }', "target": "$.l[*]"},
        ],
    )
    bad_name = await _save(forge, [{"name": "../x", "template": "{}"}])

    assert refused.status_code == 422
    assert [(p["step"], p["code"]) for p in refused.json()["detail"]["problems"]] == [
        (0, "hors_profil"),
        (1, "cible_invalide"),
    ]
    assert bad_name.json()["detail"] == {"field": "steps", "reason": "nom_d_etape"}
    assert await forge.commits() == before


async def test_deleting_a_chain_removes_its_directory(forge: Forge) -> None:
    await _save(forge, STEPS)

    deleted = await forge.client.delete(f"{ROUTE}/comptes-import", timeout=120)
    again = await forge.client.delete(f"{ROUTE}/comptes-import", timeout=120)

    assert deleted.status_code == 204
    assert (again.status_code, again.json()["detail"]) == (404, "chaine_inconnue")
    assert await forge.file("transformations/comptes-import/chain.json") is None


async def test_a_version_cannot_freeze_a_chain_broken_outside_miles(forge: Forge) -> None:
    await _save(forge, STEPS)
    path = "transformations/comptes-import/enrichir.jslt"
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}", params={"ref": "work/edition"}
    )
    broken = base64.b64encode(b'{ "pays": $.pays + 1 }').decode()
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}",
        json={"branch": "work/edition", "sha": meta.json()["sha"], "content": broken},
    )
    assert changed.status_code == 200, changed.text

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Chaîne cassée"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": "transformations/comptes-import/chain.json",
            "problems": [{"path": "enrichir", "code": "hors_profil", "detail": "operateur"}],
        }
    ]
