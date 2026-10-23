from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from miles.events.model import EventAuthor
from tests.integration.test_contracts_pg import EMPTY
from tests.integration.test_datamodels_pg import PERSONNE
from tests.integration.test_sources_pg import SOURCE
from tests.integration.work_stack import Forge, open_work_forge, register_identity, take_hold

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/branches"
MODELS = "/api/workspaces/retrait/data-models"
VERSIONS = "/api/workspaces/retrait/versions"
MODEL_PATH = "shared/messages/personne.yaml"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path, edition=False) as opened:
        yield opened


async def _create(forge: Forge, slug: str = "essai", label: str = "Essai Gael") -> httpx.Response:
    return await forge.client.post(ROUTE, json={"label": label, "slug": slug}, timeout=120)


async def _head(forge: Forge, branch: str) -> str | None:
    got = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches/{branch}")
    return got.json()["commit"]["id"] if got.status_code == 200 else None


async def test_child_branch_starts_at_the_base_head_and_is_listed_after_it(forge: Forge) -> None:
    base_head = await _head(forge, "work/atelier")

    created = await _create(forge)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert created.status_code == 201, created.text
    assert created.json() == {
        "slug": "essai",
        "label": "Essai Gael",
        "branch": "work/essai",
        "base": False,
    }
    assert await _head(forge, "work/essai") == base_head
    assert listed.json() == [
        {"slug": "atelier", "label": "atelier", "branch": "work/atelier", "base": True},
        created.json(),
    ]
    event = await forge.portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = 'workspace.branch_created'"
    )
    assert event is not None


async def _hold(forge: Forge, slug: str = "essai") -> None:
    """On ne modifie une branche enfant qu'en en ayant la main (9def0adc)."""
    await register_identity(forge.client)
    taken = await take_hold(forge.client, slug)
    assert taken.status_code == 201, taken.text


async def _publish(forge: Forge, slug: str = "essai") -> None:
    published = await forge.client.post(f"{ROUTE}/{slug}/hold/publish", timeout=120)
    assert published.status_code == 200, published.text


async def test_writes_on_a_child_branch_stay_in_it(forge: Forge) -> None:
    await _create(forge)
    await _hold(forge)
    base_commits = await forge.commits()

    written = await forge.client.post(
        MODELS,
        params={"branch": "essai"},
        json={"scope": "shared", "content": PERSONNE},
        timeout=120,
    )
    on_child = await forge.client.get(MODELS, params={"branch": "essai"}, timeout=120)
    on_base = await forge.client.get(MODELS, timeout=120)

    assert written.status_code == 201, written.text
    await _publish(forge)
    assert await forge.file(MODEL_PATH, "work/essai") == PERSONNE
    assert await forge.file(MODEL_PATH) is None
    assert await forge.commits() == base_commits
    assert [m["name"] for m in on_child.json()] == ["personne"]
    assert on_base.json() == []


async def test_versions_belong_to_their_branch_and_share_one_numbering(forge: Forge) -> None:
    await _create(forge)
    await _hold(forge)
    await forge.client.post(
        MODELS,
        params={"branch": "essai"},
        json={"scope": "shared", "content": PERSONNE},
        timeout=120,
    )
    await _publish(forge)

    base_version = await forge.client.post(VERSIONS, json={"label": "Base"}, timeout=120)
    child_version = await forge.client.post(
        VERSIONS, params={"branch": "essai"}, json={"label": "Fille"}, timeout=120
    )
    on_base = await forge.client.get(VERSIONS, timeout=120)
    on_child = await forge.client.get(VERSIONS, params={"branch": "essai"}, timeout=120)
    foreign = await forge.client.post(
        f"{VERSIONS}/1/restore", params={"branch": "essai"}, timeout=120
    )

    assert (base_version.json()["number"], child_version.json()["number"]) == (1, 2)
    assert [(v["number"], v["branch"]) for v in on_base.json()] == [(1, "work/atelier")]
    assert [(v["number"], v["branch"]) for v in on_child.json()] == [(2, "work/essai")]
    assert (foreign.status_code, foreign.json()["detail"]) == (404, "version_inconnue")


async def test_replay_and_refusals_create_nothing(forge: Forge) -> None:
    await _create(forge)
    outside = await forge.api.post(
        f"/api/v1/repos/miles/{forge.name}/branches",
        json={"new_branch_name": "work/hors-miles", "old_ref_name": "work/atelier"},
    )
    assert outside.status_code == 201, outside.text

    replay = await _create(forge)
    taken = await _create(forge, label="Autre label")
    base_taken = await _create(forge, slug="atelier")
    in_git = await _create(forge, slug="hors-miles")
    no_label = await _create(forge, slug="autre", label="  ")
    bad_slug = await _create(forge, slug="Autre!")
    unknown = await forge.client.get(MODELS, params={"branch": "inconnue"}, timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert taken.json()["detail"] == {"code": "slug_pris", "by": "Essai Gael"}
    assert base_taken.json()["detail"] == {"code": "slug_pris", "by": "atelier"}
    assert (in_git.status_code, in_git.json()["detail"]) == (
        409,
        {"code": "slug_pris", "by": "work/hors-miles"},
    )
    assert no_label.json()["detail"] == {"field": "label", "reason": "vide"}
    assert bad_slug.json()["detail"] == {"field": "slug"}
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "branche_inconnue")
    assert [b["slug"] for b in listed.json()] == ["atelier", "essai"]


async def test_child_branch_deleted_outside_miles_is_named(forge: Forge) -> None:
    await _create(forge)
    deleted = await forge.api.delete(f"/api/v1/repos/miles/{forge.name}/branches/work/essai")
    assert deleted.status_code == 204, deleted.text

    read = await forge.client.get(MODELS, params={"branch": "essai"}, timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert (read.status_code, read.json()["detail"]) == (409, "branche_de_travail_introuvable")
    assert [b["slug"] for b in listed.json()] == ["atelier", "essai"]
    assert await _head(forge, "work/essai") is None


async def test_workspace_without_base_branch_cannot_have_children(forge: Forge) -> None:
    created = await forge.client.post("/api/workspaces", json={"id": "caisse", "name": "Caisse"})
    assert created.status_code == 201

    refused = await forge.client.post(
        "/api/workspaces/caisse/branches", json={"label": "x", "slug": "x"}, timeout=120
    )

    assert (refused.status_code, refused.json()["detail"]) == (409, "depot_non_configure")


async def test_each_viewer_keeps_the_branch_they_look_at(forge: Forge) -> None:
    await _create(forge)
    service = forge.portal.app.state.branches
    bob = EventAuthor("annuaire-x", "bob")

    chosen = await forge.client.put(f"{ROUTE}/view", json={"branch": "essai"}, timeout=120)
    again = await forge.client.put(f"{ROUTE}/view", json={"branch": "atelier"}, timeout=120)
    unknown = await forge.client.put(f"{ROUTE}/view", json={"branch": "inconnue"}, timeout=120)
    await service.resolve_set_view(bob, "retrait", "essai")
    mine = await forge.client.get("/api/branch-views")

    assert (chosen.status_code, chosen.json()["slug"]) == (200, "essai")
    assert again.json()["slug"] == "atelier"
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "branche_inconnue")
    # Le choix de l'un ne change pas ce que regarde l'autre.
    assert mine.json() == {"retrait": "atelier"}
    assert await service.resolve_views(bob) == {"retrait": "essai"}


async def test_the_root_refuses_every_content_write_but_can_be_frozen(forge: Forge) -> None:
    # La racine est en lecture seule (story dca0eb0e) : on modifie dans une branche enfant.
    workspace = "/api/workspaces/retrait"
    writes = [
        ("POST", MODELS, {"scope": "shared", "content": PERSONNE}),
        ("DELETE", f"{MODELS}/shared/personne", None),
        ("POST", f"{workspace}/contracts", {"slug": "suivi", "label": "Suivi", "sens": "sortant"}),
        ("POST", f"{workspace}/contracts/suivi/versions", {"content": EMPTY}),
        ("DELETE", f"{workspace}/contracts/suivi", None),
        ("PUT", f"{workspace}/transformations/import", {"label": "Import", "steps": []}),
        ("DELETE", f"{workspace}/transformations/import", None),
        ("POST", f"{workspace}/sources", SOURCE),
        ("PUT", f"{workspace}/sources/comptes", SOURCE),
        ("DELETE", f"{workspace}/sources/comptes", None),
    ]
    before = await forge.commits()

    version = await forge.client.post(VERSIONS, json={"label": "Racine"}, timeout=120)
    restore = await forge.client.post(f"{VERSIONS}/1/restore", timeout=120)
    refused = [
        await forge.client.request(method, path, json=body, timeout=120)
        for method, path, body in writes
    ]
    child = await _create(forge)

    assert version.status_code == 201, version.text
    assert (restore.status_code, restore.json()["detail"]) == (409, "branche_racine_lecture_seule")
    for (method, path, _), response in zip(writes, refused, strict=True):
        assert (method, path, response.status_code, response.json()["detail"]) == (
            method,
            path,
            409,
            "branche_racine_lecture_seule",
        )
    assert child.status_code == 201, child.text
    assert await forge.commits() == before
