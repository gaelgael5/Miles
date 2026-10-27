from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.work_stack import ROOT, Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/domains"


async def add_domain(forge: Forge, name: str = "suivi", **params: str) -> httpx.Response:
    """Un modèle de domaine suppose son domaine déclaré (story 7fa00f56)."""
    return await forge.client.post(ROUTE, json={"name": name}, params=params, timeout=120)


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def test_a_domain_is_added_once_then_listed(forge: Forge) -> None:
    empty = await forge.client.get(ROUTE, timeout=120)
    added = await add_domain(forge)
    before = await forge.commits()
    replay = await add_domain(forge)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert empty.json() == []
    assert (added.status_code, added.json()) == (201, {"name": "suivi"})
    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert await forge.commits() == before
    assert listed.json() == [{"name": "suivi"}]
    assert await forge.file("domains/suivi/.gitkeep") == ""
    events = await forge.portal.pool.fetch(
        "SELECT properties->>'domain' AS domain FROM events WHERE type = 'domain.created'"
    )
    assert [e["domain"] for e in events] == ["suivi"]


@pytest.mark.parametrize("name", ["", "Suivi", "suivi.colis", "..", "a/b", "-suivi", "x" * 64, "é"])
async def test_an_invalid_name_is_refused_before_touching_the_repository(
    forge: Forge, name: str
) -> None:
    before = await forge.commits()

    refused = await add_domain(forge, name)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "name"})
    assert await forge.commits() == before


async def test_the_root_branch_lists_domains_but_takes_none(forge: Forge) -> None:
    listed = await forge.client.get(ROUTE, params={"branch": ROOT}, timeout=120)
    refused = await add_domain(forge, branch=ROOT)

    assert listed.status_code == 200, listed.text
    assert (refused.status_code, refused.json()["detail"]) == (409, "branche_racine_lecture_seule")
    assert await forge.file("domains/suivi/.gitkeep", f"back/retrait/{ROOT}") is None
