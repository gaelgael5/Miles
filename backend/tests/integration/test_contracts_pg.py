from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/contracts"
SUIVI = """openapi: 3.0.3
info:
  title: Suivi des demandes
  version: "1.2"
paths:
  /demandes:
    get:
      operationId: listerDemandes
      responses:
        "200": {description: ok}
"""
EMPTY = 'openapi: 3.1.0\ninfo: {title: Vide, version: "1"}\npaths: {}\n'


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _import(
    forge: Forge, content: str, slug: str, sens: str | None = "sortant"
) -> httpx.Response:
    body = {"slug": slug, "content": content} | ({"sens": sens} if sens else {})
    return await forge.client.post(ROUTE, json=body, timeout=120)


async def test_contract_is_proposed_a_slug_then_imported_under_the_chosen_one(
    forge: Forge,
) -> None:
    preview = await forge.client.post(f"{ROUTE}/preview", json={"content": SUIVI})

    imported = await _import(forge, SUIVI, "suivi")
    listed = await forge.client.get(ROUTE, timeout=120)
    detail = await forge.client.get(f"{ROUTE}/suivi", timeout=120)

    assert preview.json()["slug"] == "suivi-des-demandes"
    assert imported.status_code == 201, imported.text
    assert imported.json() == {
        "slug": "suivi",
        "sens": "sortant",
        "title": "Suivi des demandes",
        "operations": 1,
        "warnings": [],
    }
    assert await forge.file("contracts/suivi/v1.yaml") == SUIVI
    assert await forge.file("contracts/suivi/contract.yaml") == "slug: suivi\nsens: sortant\n"
    assert [c["slug"] for c in listed.json()] == ["suivi"]
    assert detail.json()["operation_list"] == [
        {"method": "get", "path": "/demandes", "operation_id": "listerDemandes"}
    ]


async def test_slug_is_frozen_and_the_direction_cannot_change(forge: Forge) -> None:
    await _import(forge, SUIVI, "suivi")

    renamed = await forge.client.patch(f"{ROUTE}/suivi", json={"slug": "autre"})
    turned = await forge.client.patch(f"{ROUTE}/suivi", json={"sens": "entrant"})

    assert (renamed.status_code, renamed.json()["detail"]) == (409, "slug_fige")
    assert (turned.status_code, turned.json()["detail"]) == (409, "sens_fige")
    assert await forge.file("contracts/autre/v1.yaml") is None


async def test_replay_writes_nothing_and_a_taken_slug_names_its_occupant(forge: Forge) -> None:
    await _import(forge, SUIVI, "suivi")
    before = await forge.commits()

    replay = await _import(forge, SUIVI, "suivi")
    taken = await _import(forge, EMPTY, "suivi")
    other_direction = await _import(forge, SUIVI, "suivi", sens="entrant")

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert taken.json()["detail"] == {"code": "slug_pris", "by": "Suivi des demandes"}
    assert other_direction.status_code == 409
    assert await forge.commits() == before


async def test_contract_without_operation_is_accepted_and_flagged(forge: Forge) -> None:
    imported = await _import(forge, EMPTY, "vide", sens="entrant")

    assert imported.status_code == 201
    assert imported.json()["warnings"] == ["aucune_operation"]


async def test_refusals_write_nothing_and_say_why(forge: Forge) -> None:
    before = await forge.commits()

    no_direction = await _import(forge, SUIVI, "suivi", sens=None)
    empty_slug = await _import(forge, SUIVI, "   ")
    bad_slug = await _import(forge, SUIVI, "Suivi!")
    unreadable = await _import(forge, "openapi: [\n", "autre")
    swagger = await _import(forge, "swagger: '2.0'\ninfo: {title: x}\n", "autre")
    invalid = await _import(forge, EMPTY.replace(', version: "1"', ""), "autre")

    assert no_direction.json()["detail"] == {"field": "sens"}
    assert empty_slug.json()["detail"] == {"field": "slug", "reason": "vide"}
    assert bad_slug.json()["detail"] == {"field": "slug"}
    assert unreadable.json()["detail"]["code"] == "openapi_illisible"
    assert unreadable.json()["detail"]["line"] is not None
    assert swagger.json()["detail"] == {
        "code": "version_non_prise_en_charge",
        "found": "2.0",
        "accepted": ["3.0", "3.1"],
    }
    assert invalid.json()["detail"]["code"] == "openapi_invalide"
    assert await forge.commits() == before


async def test_a_version_cannot_freeze_a_contract_broken_outside_miles(forge: Forge) -> None:
    await _import(forge, SUIVI, "suivi")
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        params={"ref": "work/atelier"},
    )
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        json={
            "branch": "work/atelier",
            "sha": meta.json()["sha"],
            # « slug: suivi », « sens: lateral » : un sens hors liste, en base64.
            "content": "c2x1Zzogc3VpdmkKc2VuczogbGF0ZXJhbAo=",
        },
    )
    assert changed.status_code == 200, changed.text

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Contrat cassé"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": "contracts/suivi/contract.yaml",
            "problems": [{"path": "", "code": "metadonnees_de_contrat_invalides", "detail": None}],
        }
    ]
