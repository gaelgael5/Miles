from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.events.model import EventAuthor
from miles.workshop.holds import AlreadyHoldingError, BranchHeldError
from tests.integration.git_stack import env
from tests.integration.test_contracts_pg import EMPTY
from tests.integration.test_datamodels_pg import PERSONNE, body_of
from tests.integration.test_sources_pg import SOURCE
from tests.integration.work_stack import (
    EDITED,
    ROOT,
    Forge,
    open_work_forge,
    register_identity,
    take_hold,
)

pytestmark = pytest.mark.integration

WS = "/api/workspaces/retrait"
HOLD = f"{WS}/branches/edition/hold"
MODELS = f"{WS}/data-models"
MODEL_PATH = "shared/messages/personne.yaml"
BOB = EventAuthor("annuaire-x", "bob")


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path, hold=False) as opened:
        yield opened


async def _with_identity(forge: Forge, person: EventAuthor = BOB) -> None:
    service = forge.portal.app.state.git_identities
    await service.resolve_register(person, "forge", env("MILES_TEST_GITEA_TOKEN"))


async def _label(forge: Forge) -> str:
    me = (await forge.api.get("/api/v1/user")).json()
    return f"{me.get('full_name') or me['login']} ({me['login']})"


async def _remote_head(forge: Forge, branch: str = EDITED) -> str:
    got = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches/{branch}")
    return str(got.json()["commit"]["id"])


async def test_taking_the_hold_shows_who_has_it_and_refuses_anyone_else(forge: Forge) -> None:
    await register_identity(forge.client)
    await _with_identity(forge)
    holds = forge.portal.app.state.branch_holds

    before = await forge.client.get(f"{WS}/holds")
    taken = await take_hold(forge.client)
    replay = await take_hold(forge.client)
    listed = await forge.client.get(f"{WS}/holds")
    status = await forge.client.get(HOLD)
    with pytest.raises(BranchHeldError) as refused:
        await holds.resolve_take(BOB, "retrait", "edition")

    label = await _label(forge)
    assert before.json() == []
    assert (taken.status_code, replay.status_code) == (201, 200)
    assert [(h["slug"], h["holder"], h["mine"]) for h in listed.json()] == [
        ("edition", label, True)
    ]
    assert status.json()["unpublished"] == 0
    assert refused.value.holder == label


async def test_two_simultaneous_requests_never_both_win(forge: Forge) -> None:
    await register_identity(forge.client)
    await _with_identity(forge)
    holds = forge.portal.app.state.branch_holds

    results = await asyncio.gather(
        take_hold(forge.client),
        holds.resolve_take(BOB, "retrait", "edition"),
        return_exceptions=True,
    )

    admin_won = getattr(results[0], "status_code", None) == 201
    bob_won = not isinstance(results[1], BaseException)
    assert admin_won != bob_won, results
    if admin_won:
        assert isinstance(results[1], BranchHeldError)
    else:
        assert results[0].json()["detail"]["code"] == "branche_tenue"  # type: ignore[union-attr]
    assert await forge.portal.pool.fetchval("SELECT count(*) FROM branch_holds") == 1


async def test_one_branch_per_person_and_no_hold_without_pat_or_on_the_root(forge: Forge) -> None:
    other = await forge.client.post(
        f"{WS}/branches", json={"label": "Autre", "slug": "autre"}, timeout=120
    )
    assert other.status_code == 201, other.text

    without_pat = await take_hold(forge.client)
    await register_identity(forge.client)
    root = await take_hold(forge.client, ROOT)
    assert (await take_hold(forge.client)).status_code == 201
    second = await take_hold(forge.client, "autre")
    await _with_identity(forge)
    await forge.portal.app.state.branch_holds.resolve_take(BOB, "retrait", "autre")
    with pytest.raises(AlreadyHoldingError):
        await forge.portal.app.state.branch_holds.resolve_take(BOB, "retrait", "edition")

    assert (without_pat.status_code, without_pat.json()["detail"]) == (409, "identite_git_requise")
    assert (root.status_code, root.json()["detail"]) == (409, "branche_racine_lecture_seule")
    assert (second.status_code, second.json()["detail"]) == (
        409,
        {"code": "deja_une_branche", "workspace_id": "retrait", "branch": "edition"},
    )


async def test_without_the_hold_every_workshop_write_is_refused_but_reads_stay_open(
    forge: Forge,
) -> None:
    writes = [
        ("POST", MODELS, body_of(PERSONNE)),
        ("DELETE", f"{MODELS}/shared/personne", None),
        ("POST", f"{WS}/contracts", {"slug": "suivi", "label": "Suivi", "sens": "externe"}),
        ("POST", f"{WS}/contracts/suivi/versions", {"content": EMPTY}),
        ("DELETE", f"{WS}/contracts/suivi", None),
        ("PUT", f"{WS}/transformations/import", {"label": "Import", "steps": []}),
        ("DELETE", f"{WS}/transformations/import", None),
        ("POST", f"{WS}/sources", SOURCE),
        ("PUT", f"{WS}/sources/comptes", SOURCE),
        ("DELETE", f"{WS}/sources/comptes", None),
        ("POST", f"{WS}/versions", {"label": "Essai"}),
        ("POST", f"{WS}/versions/1/restore", None),
    ]
    before = await forge.commits()

    refused = [
        await forge.client.request(method, path, json=body, timeout=120)
        for method, path, body in writes
    ]
    reads = [await forge.client.get(path) for path in (MODELS, f"{WS}/versions", f"{WS}/sources")]

    for (method, path, _), response in zip(writes, refused, strict=True):
        assert (method, path, response.status_code, response.json()["detail"]) == (
            method,
            path,
            409,
            "prise_de_main_requise",
        )
    assert [r.status_code for r in reads] == [200, 200, 200]
    assert await forge.commits() == before


async def test_a_change_is_local_and_only_its_author_sees_it_until_published(
    forge: Forge,
) -> None:
    await register_identity(forge.client)
    assert (await take_hold(forge.client)).status_code == 201
    head = await _remote_head(forge)

    created = await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)
    mine = await forge.client.get(MODELS)
    others = await forge.portal.app.state.data_models.resolve_list(BOB, "retrait", branch="edition")
    status = await forge.client.get(HOLD)
    remote_before = await forge.remote_file(MODEL_PATH)
    published = await forge.client.post(f"{HOLD}/publish", timeout=120)
    again = await forge.client.post(f"{HOLD}/publish", timeout=120)

    commit = (
        await forge.api.get(
            f"/api/v1/repos/miles/{forge.name}/git/commits/{await _remote_head(forge)}"
        )
    ).json()["commit"]
    me = (await forge.api.get("/api/v1/user")).json()
    assert created.status_code == 201, created.text
    assert [m["path"] for m in mine.json()] == [MODEL_PATH]
    assert others == []
    assert status.json()["unpublished"] == 1
    assert remote_before is None
    assert (published.json(), again.json()) == ({"published": 1}, {"published": 0})
    assert await forge.remote_file(MODEL_PATH) == PERSONNE
    assert await _remote_head(forge) != head
    identity = (me.get("full_name") or me["login"], me["email"])
    assert (commit["author"]["name"], commit["author"]["email"]) == identity
    assert (commit["committer"]["name"], commit["committer"]["email"]) == identity


async def test_a_refused_publication_loses_nothing_and_says_why(forge: Forge) -> None:
    await register_identity(forge.client)
    assert (await take_hold(forge.client)).status_code == 201
    await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)
    outside = await forge.api.post(
        f"/api/v1/repos/miles/{forge.name}/contents/hors-miles.txt",
        json={
            "content": base64.b64encode(b"x\n").decode(),
            "branch": EDITED,
            "message": "hors Miles",
        },
    )
    assert outside.status_code == 201, outside.text

    refused = await forge.client.post(f"{HOLD}/publish", timeout=120)
    release = await forge.client.delete(HOLD, timeout=120)
    status = await forge.client.get(HOLD)

    assert (refused.status_code, refused.json()["detail"]) == (409, "branche_modifiee")
    assert (release.status_code, release.json()["detail"]) == (409, "branche_modifiee")
    assert status.json()["unpublished"] == 1
    assert status.json()["hold"]["mine"] is True
    assert await forge.remote_file(MODEL_PATH) is None


async def test_releasing_publishes_frees_the_branch_and_removes_the_space(forge: Forge) -> None:
    await register_identity(forge.client)
    assert (await take_hold(forge.client)).status_code == 201
    await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)
    space = forge.portal.app.state.branch_holds.branches.holds.directory("retrait", "edition")
    existed = space.is_dir()

    released = await forge.client.delete(HOLD, timeout=120)
    replay = await forge.client.delete(HOLD, timeout=120)
    events = await forge.portal.pool.fetch(
        "SELECT type, author_directory, author_subject FROM events"
        " WHERE type LIKE 'branch_hold.%' ORDER BY written_at"
    )

    assert existed and not space.exists()
    assert (released.json(), replay.json()) == ({"released": True}, {"released": False})
    assert await forge.remote_file(MODEL_PATH) == PERSONNE
    assert (await forge.client.get(f"{WS}/holds")).json() == []
    assert [(e["type"], e["author_subject"]) for e in events] == [
        ("branch_hold.taken", "admin"),
        ("branch_hold.published", "admin"),
        ("branch_hold.released", "admin"),
    ]


async def test_a_version_needs_everything_published_first(forge: Forge) -> None:
    await register_identity(forge.client)
    assert (await take_hold(forge.client)).status_code == 201
    await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)

    early = await forge.client.post(f"{WS}/versions", json={"label": "Trop tôt"}, timeout=120)
    # L'écran pose la même question avant le clic, et reçoit la même raison.
    blocked = await forge.client.get(f"{WS}/versions/freezable", timeout=120)
    await forge.client.post(f"{HOLD}/publish", timeout=120)
    freed = await forge.client.get(f"{WS}/versions/freezable", timeout=120)
    saved = await forge.client.post(f"{WS}/versions", json={"label": "Publiée"}, timeout=120)

    assert (early.status_code, early.json()["detail"]) == (409, "publication_requise")
    assert blocked.json() == {"ok": False, "reason": "publication_requise"}
    assert freed.json() == {"ok": True, "reason": None}
    assert saved.status_code == 201, saved.text
    assert saved.json()["commit"] == await _remote_head(forge)


async def test_the_pat_cannot_be_removed_while_holding_a_branch(forge: Forge) -> None:
    await register_identity(forge.client)
    assert (await take_hold(forge.client)).status_code == 201

    refused = await forge.client.delete("/api/auth/me/git-identities/forge")
    await forge.client.delete(HOLD, timeout=120)
    removed = await forge.client.delete("/api/auth/me/git-identities/forge")

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        {"code": "prise_de_main_en_cours", "workspace_id": "retrait", "branch": "edition"},
    )
    assert removed.status_code == 204
