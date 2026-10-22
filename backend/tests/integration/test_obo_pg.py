from __future__ import annotations

import time
from datetime import timedelta

import httpx
import pytest

from miles.auth.sessions import OIDC_KIND, SESSION_COOKIE, db_create_session, new_session_token
from miles.obo.signature import sign_actor
from tests.integration.portal_stack import utc_now
from tests.integration.test_api_keys_pg import Stack, _call, _issue, _result, bearer, stack

pytestmark = pytest.mark.integration
__all__ = ["stack"]

IDENTITY = "/api/auth/me/identity"
GUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


async def _oidc_client(stack: Stack, subject: str, name: str) -> httpx.AsyncClient:
    token, digest = new_session_token()
    await db_create_session(
        stack.portal.pool,
        digest,
        OIDC_KIND,
        subject,
        utc_now() + timedelta(hours=1),
        directory="maison",
        display_name=name,
        email=f"{subject}@exemple.invalid",
    )
    client = stack.portal.anonymous()
    client.cookies.set(SESSION_COOKIE, token)
    return client


def _signed(key: str, actor: str, *, at: int | None = None, forged: bool = False) -> dict[str, str]:
    timestamp = int(time.time()) if at is None else at
    signature = sign_actor(actor, timestamp, "autre-cle" if forged else key)
    return {
        "x-portal-actor": actor,
        "x-portal-actor-timestamp": str(timestamp),
        "x-portal-actor-signature": signature,
    }


async def test_a_person_sets_changes_and_removes_their_actor_guid(stack: Stack) -> None:
    async with await _oidc_client(stack, "sub-lea", "Léa") as lea:
        empty = await lea.get(IDENTITY)
        set_ = await lea.put(IDENTITY, json={"actor": f"  {GUID} "})
        read = await lea.get(IDENTITY)
        invalid = await lea.put(IDENTITY, json={"actor": "pas un guid !"})
        removed = await lea.delete(IDENTITY)
        after = await lea.get(IDENTITY)

    assert empty.json() == {"actor": None}
    assert (set_.status_code, set_.json()) == (200, {"actor": GUID})
    assert read.json() == {"actor": GUID}
    assert (invalid.status_code, invalid.json()["detail"]) == (422, {"field": "actor"})
    assert removed.status_code == 204 and after.json() == {"actor": None}


async def test_a_guid_already_taken_by_someone_else_is_refused(stack: Stack) -> None:
    assert (await stack.admin.put(IDENTITY, json={"actor": GUID})).status_code == 200
    async with await _oidc_client(stack, "sub-lea", "Léa") as lea:
        taken = await lea.put(IDENTITY, json={"actor": GUID})

    assert (taken.status_code, taken.json()["detail"]) == (409, "identite_prise")


async def test_a_signed_known_actor_is_who_the_call_is_made_for(stack: Stack) -> None:
    secret = (await _issue(stack, {"retrait": "lecture"}))["secret"]
    async with await _oidc_client(stack, "sub-lea", "Léa") as lea:
        await lea.put(IDENTITY, json={"actor": GUID})

    signed = _result(await _call(stack, "whoami", bearer(secret) | _signed(secret, GUID)))
    alone = _result(await _call(stack, "whoami", bearer(secret)))

    assert signed == {"key": "Gateway yoops", "acting_for": "Léa"}
    assert alone == {"key": "Gateway yoops", "acting_for": None}


@pytest.mark.parametrize("case", ["forged", "stale", "unknown"])
async def test_forged_stale_or_unknown_actor_falls_back_to_the_key_never_401(
    stack: Stack, case: str
) -> None:
    secret = (await _issue(stack, {"retrait": "lecture"}))["secret"]
    await stack.admin.put(IDENTITY, json={"actor": GUID})
    headers = {
        "forged": _signed(secret, GUID, forged=True),
        "stale": _signed(secret, GUID, at=int(time.time()) - 301),
        "unknown": _signed(secret, "inconnu-de-miles"),
    }[case]

    served = _result(await _call(stack, "whoami", bearer(secret) | headers))

    assert served == {"key": "Gateway yoops", "acting_for": None}


async def test_an_actor_in_the_arguments_is_never_taken(stack: Stack) -> None:
    secret = (await _issue(stack, {"retrait": "lecture"}))["secret"]
    await stack.admin.put(IDENTITY, json={"actor": GUID})

    response = await _call(stack, "whoami", bearer(secret), {"x-portal-actor": GUID})

    body = response.json()["result"]
    assert body.get("isError") is True or body["structuredContent"]["acting_for"] is None
