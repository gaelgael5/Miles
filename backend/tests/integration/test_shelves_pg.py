from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.events.model import EventAuthor
from miles.identities.service import _aad
from miles.secrets.model import Secret
from miles.workshop.shelving import ShelfConflictError
from tests.integration.git_stack import env
from tests.integration.test_datamodels_pg import PERSONNE
from tests.integration.work_stack import EDITED, Forge, open_work_forge

pytestmark = pytest.mark.integration

WS = "/api/workspaces/retrait"
UNLOCK = f"{WS}/branches/edition/hold/unlock"
MODEL_PATH = "shared/messages/personne.yaml"
BOB = EventAuthor("annuaire-x", "bob")


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path, hold=False) as opened:
        state = opened.portal.app.state
        await state.git_identities.resolve_register(BOB, "forge", env("MILES_TEST_GITEA_TOKEN"))
        await state.branch_holds.resolve_take(BOB, "retrait", "edition")
        yield opened


async def _bob_writes(forge: Forge, content: str = PERSONNE) -> None:
    models = forge.portal.app.state.data_models
    await models.resolve_create(BOB, "retrait", "shared", content, branch="edition")


async def _shelf_name(forge: Forge) -> str:
    login = (await forge.api.get("/api/v1/user")).json()["login"]
    return f"shelve/{login}/edition"


async def _tip(forge: Forge, branch: str) -> str | None:
    got = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches/{branch}")
    return str(got.json()["commit"]["id"]) if got.status_code == 200 else None


async def _outside(forge: Forge, path: str, content: str) -> None:
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}", params={"ref": EDITED}
    )
    body = {"branch": EDITED, "content": base64.b64encode(content.encode()).decode()}
    if meta.status_code == 200:
        changed = await forge.api.put(
            f"/api/v1/repos/miles/{forge.name}/contents/{path}",
            json=body | {"sha": meta.json()["sha"]},
        )
    else:
        changed = await forge.api.post(
            f"/api/v1/repos/miles/{forge.name}/contents/{path}", json=body
        )
    assert changed.status_code in (200, 201), changed.text


async def test_unlocking_shelves_unpublished_work_on_the_forge_then_frees_the_branch(
    forge: Forge,
) -> None:
    await _bob_writes(forge)
    space = forge.portal.app.state.branch_holds.branches.holds.directory("retrait", "edition")
    head = await _tip(forge, EDITED)

    unlocked = await forge.client.post(UNLOCK, timeout=120)
    listed = await forge.client.get(f"{WS}/shelves")
    bobs = await forge.portal.app.state.shelves.resolve_mine(BOB)
    event = await forge.portal.pool.fetchrow(
        "SELECT author_subject, properties FROM events WHERE type = 'branch_hold.unlocked'"
    )

    name = await _shelf_name(forge)
    assert unlocked.status_code == 200, unlocked.text
    shelf = unlocked.json()["shelf"]
    assert (shelf["shelf_branch"], shelf["mine"]) == (name, False)
    assert await forge.remote_file(MODEL_PATH, name) == PERSONNE
    assert await _tip(forge, EDITED) == head
    assert not space.exists()
    assert (await forge.client.get(f"{WS}/holds")).json() == []
    assert [s["shelf_branch"] for s in listed.json()] == [name]
    assert [s.shelf_branch for s in bobs] == [name]
    assert event is not None and event["author_subject"] == "admin"
    assert name in event["properties"]


async def test_nothing_to_shelve_simply_frees_the_branch(forge: Forge) -> None:
    unlocked = await forge.client.post(UNLOCK, timeout=120)

    assert unlocked.json() == {"shelf": None}
    assert await _tip(forge, await _shelf_name(forge)) is None
    assert (await forge.client.get(f"{WS}/holds")).json() == []


async def test_a_refused_personal_token_keeps_everything_and_says_so(forge: Forge) -> None:
    await _bob_writes(forge)
    state = forge.portal.app.state
    sealed = state.git_identities.cipher.seal(_aad(BOB, "forge"), Secret("jeton-revoque"))
    await forge.portal.pool.execute(
        "UPDATE user_git_identities SET key_version = $1, nonce = $2, ciphertext = $3"
        " WHERE viewer_subject = 'bob'",
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
    )
    space = state.branch_holds.branches.holds.directory("retrait", "edition")

    refused = await forge.client.post(UNLOCK, timeout=120)

    assert (refused.status_code, refused.json()["detail"]) == (409, "jeton_personnel_refuse")
    assert [h["holder"] for h in (await forge.client.get(f"{WS}/holds")).json()] != []
    assert space.is_dir()
    assert await _tip(forge, await _shelf_name(forge)) is None


async def test_an_existing_shelf_is_never_overwritten(forge: Forge) -> None:
    await _bob_writes(forge)
    name = await _shelf_name(forge)
    made = await forge.api.post(
        f"/api/v1/repos/miles/{forge.name}/branches",
        json={"new_branch_name": name, "old_ref_name": "work/atelier"},
    )
    assert made.status_code == 201, made.text
    before = await _tip(forge, name)

    refused = await forge.client.post(UNLOCK, timeout=120)

    assert (refused.status_code, refused.json()["detail"]) == (409, "rangement_existant")
    assert await _tip(forge, name) == before
    assert len((await forge.client.get(f"{WS}/holds")).json()) == 1


async def test_taking_over_again_merges_the_shelf_into_the_updated_branch(forge: Forge) -> None:
    await _bob_writes(forge)
    assert (await forge.client.post(UNLOCK, timeout=120)).status_code == 200
    await _outside(forge, "ailleurs.txt", "hors Miles\n")
    state = forge.portal.app.state

    await state.branch_holds.resolve_take(BOB, "retrait", "edition")
    seen = await state.data_models.resolve_list(BOB, "retrait", branch="edition")
    status = await state.branch_holds.resolve_status(BOB, "retrait", "edition")

    assert [m.path for m in seen] == [MODEL_PATH]
    assert status.unpublished is not None and status.unpublished >= 1
    assert await _tip(forge, await _shelf_name(forge)) is None
    assert await state.shelves.resolve_mine(BOB) == []
    resumed = await forge.portal.pool.fetchval(
        "SELECT count(*) FROM events WHERE type = 'branch_hold.resumed'"
    )
    assert resumed == 1


async def test_a_conflicting_resume_names_the_files_and_leaves_the_shelf(forge: Forge) -> None:
    await _bob_writes(forge)
    assert (await forge.client.post(UNLOCK, timeout=120)).status_code == 200
    await _outside(forge, MODEL_PATH, PERSONNE + "  autre:\n    type: chaine\n")
    state = forge.portal.app.state

    with pytest.raises(ShelfConflictError) as conflict:
        await state.branch_holds.resolve_take(BOB, "retrait", "edition")

    assert conflict.value.files == [MODEL_PATH]
    assert (await forge.client.get(f"{WS}/holds")).json() == []
    assert await _tip(forge, await _shelf_name(forge)) is not None
    assert len(await state.shelves.resolve_mine(BOB)) == 1
