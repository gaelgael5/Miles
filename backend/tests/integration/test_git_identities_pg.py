from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.events.model import LOCAL_DIRECTORY, EventAuthor
from tests.integration.git_stack import env
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/auth/me/git-identities"
ADMIN = EventAuthor(LOCAL_DIRECTORY, "admin")


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path, hold=False) as opened:
        yield opened


async def test_personal_token_is_checked_with_the_forge_then_kept_without_being_shown(
    forge: Forge,
) -> None:
    token = env("MILES_TEST_GITEA_TOKEN")
    me = await forge.api.get("/api/v1/user")

    before = await forge.client.get(ROUTE)
    registered = await forge.client.put(f"{ROUTE}/forge", json={"token": token}, timeout=60)
    listed = await forge.client.get(ROUTE)
    stored = await forge.portal.pool.fetchrow("SELECT * FROM user_git_identities")

    assert [(i["connection_id"], i["registered"]) for i in before.json()] == [("forge", False)]
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["account"]["login"] == me.json()["login"]
    assert body["account"]["email"] == me.json()["email"]
    assert body["repositories"] == [
        {"workspace_id": "retrait", "workspace_name": "Nom retrait", "can_write": True}
    ]
    assert listed.json() == [body]
    # Le jeton n'est ni dans les réponses, ni en clair dans la ligne.
    assert token not in registered.text + listed.text
    assert stored is not None and token.encode() not in bytes(stored["ciphertext"])
    service = forge.portal.app.state.git_identities
    assert (await service.resolve_token(ADMIN, "forge")).reveal() == token


async def test_refused_token_is_not_kept_and_says_why(forge: Forge) -> None:
    refused = await forge.client.put(f"{ROUTE}/forge", json={"token": "pas-un-jeton"}, timeout=60)
    empty = await forge.client.put(f"{ROUTE}/forge", json={"token": "   "})
    unknown = await forge.client.put(f"{ROUTE}/inconnue", json={"token": "x"})

    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        {"code": "verification_impossible", "reason": "jeton_refuse"},
    )
    assert empty.json()["detail"] == {"field": "token"}
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "connexion_inconnue")
    assert await forge.portal.pool.fetchval("SELECT count(*) FROM user_git_identities") == 0


async def test_each_person_has_only_their_own_identity_and_removal_is_journaled(
    forge: Forge,
) -> None:
    service = forge.portal.app.state.git_identities
    bob = EventAuthor("annuaire-x", "bob")
    await forge.client.put(
        f"{ROUTE}/forge", json={"token": env("MILES_TEST_GITEA_TOKEN")}, timeout=60
    )

    bob_view = await service.resolve_list(bob)
    removed = await forge.client.delete(f"{ROUTE}/forge")
    again = await forge.client.delete(f"{ROUTE}/forge")
    events = await forge.portal.pool.fetch(
        "SELECT type, properties FROM events"
        " WHERE type LIKE 'user.git_identity%' ORDER BY written_at"
    )

    assert [i.account for i in bob_view] == [None]
    assert await service.resolve_token(bob, "forge") is None
    assert (removed.status_code, again.status_code) == (204, 204)
    assert await service.resolve_token(ADMIN, "forge") is None
    assert [e["type"] for e in events] == [
        "user.git_identity_registered",
        "user.git_identity_removed",
    ]
    assert all(env("MILES_TEST_GITEA_TOKEN") not in str(e["properties"]) for e in events)
