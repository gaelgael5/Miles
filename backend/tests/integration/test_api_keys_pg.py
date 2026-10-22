from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.git_stack import create_workspace, wire_git
from tests.integration.portal_stack import PortalStack, open_portal_stack

pytestmark = pytest.mark.integration

ROUTE = "/api/api-keys"
MCP = "/mcp/"
ACCEPT = {"Accept": "application/json, text/event-stream"}


@dataclass
class Stack:
    portal: PortalStack
    mcp: httpx.AsyncClient

    @property
    def admin(self) -> httpx.AsyncClient:
        return self.portal.client


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[Stack]:
    async with open_portal_stack(blank_db, tmp_path) as portal:
        wire_git(portal, ())
        for wid in ("retrait", "caisse", "stock"):
            assert (await create_workspace(portal.client, wid)).status_code == 201
        async with running_mcp(portal), portal.anonymous() as mcp:
            yield Stack(portal, mcp)


@asynccontextmanager
async def running_mcp(portal: PortalStack) -> AsyncIterator[None]:
    """Le gestionnaire de sessions MCP, comme dans la durée de vie d'app.py.

    Dans une tâche à lui : il ouvre une portée d'annulation anyio qui doit se refermer
    dans la tâche qui l'a ouverte, et pytest-asyncio démonte une fixture dans une autre.
    """
    started, stop = asyncio.Event(), asyncio.Event()

    async def serve() -> None:
        async with portal.app.state.mcp.session_manager.run():
            started.set()
            await stop.wait()

    task = asyncio.create_task(serve())
    await started.wait()
    try:
        yield
    finally:
        stop.set()
        await task


async def _issue(stack: Stack, grants: dict[str, str], label: str = "Gateway yoops") -> Any:
    body = {"label": label, "grants": [{"workspace_id": w, "access": a} for w, a in grants.items()]}
    issued = await stack.admin.post(ROUTE, json=body)
    assert issued.status_code == 201, issued.text
    return issued.json()


async def _call(
    stack: Stack, tool: str, headers: dict[str, str], arguments: dict[str, Any] | None = None
) -> httpx.Response:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }
    return await stack.mcp.post(MCP, json=message, headers=ACCEPT | headers)


def _result(response: httpx.Response) -> Any:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result.get("isError") is not True, result
    return result["structuredContent"]["result"]


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_issued_key_is_shown_once_then_only_by_its_prefix(stack: Stack) -> None:
    issued = await _issue(stack, {"retrait": "lecture", "caisse": "ecriture"})
    listed = await stack.admin.get(ROUTE)

    secret, key = issued["secret"], issued["key"]
    assert secret.startswith("mlk_") and len(secret) == 47
    assert key["prefix"] == secret[:12]
    assert key["grants"] == [
        {"workspace_id": "caisse", "access": "ecriture"},
        {"workspace_id": "retrait", "access": "lecture"},
    ]
    assert listed.json() == [key]
    assert secret not in listed.text
    stored = await stack.portal.pool.fetchrow("SELECT * FROM api_keys")
    assert stored is not None and secret.encode() not in bytes(stored["digest"])
    assert secret not in str(dict(stored))


async def test_key_sees_only_its_workspaces_through_either_header(stack: Stack) -> None:
    secret = (await _issue(stack, {"retrait": "lecture", "caisse": "ecriture"}))["secret"]

    by_bearer = _result(await _call(stack, "list_workspaces", bearer(secret)))
    by_header = _result(await _call(stack, "list_workspaces", {"X-API-Key": secret}))

    assert by_bearer == by_header
    expected = [("caisse", "ecriture"), ("retrait", "lecture")]
    assert [(w["id"], w["access"]) for w in by_bearer] == expected
    assert "stock" not in str(by_bearer)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer mlk_" + "A" * 43},
        {"Authorization": "Basic YWRtaW46YWRtaW4="},
        {"X-API-Key": "pas-une-cle"},
    ],
)
async def test_missing_unknown_or_malformed_key_gets_one_and_the_same_refusal(
    stack: Stack, headers: dict[str, str]
) -> None:
    refused = await _call(stack, "list_workspaces", headers)

    assert (refused.status_code, refused.json()) == (401, {"detail": "cle_requise"})


async def test_key_in_the_url_or_two_different_keys_open_nothing(stack: Stack) -> None:
    secret = (await _issue(stack, {"retrait": "lecture"}))["secret"]
    other = (await _issue(stack, {"retrait": "lecture"}, label="Autre"))["secret"]

    in_url = await stack.mcp.post(
        f"{MCP}?api_key={secret}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=ACCEPT,
    )
    two = await _call(stack, "list_workspaces", bearer(secret) | {"X-API-Key": other})

    assert (in_url.status_code, two.status_code) == (401, 401)


async def test_revocation_and_withdrawn_grants_apply_at_the_next_call(stack: Stack) -> None:
    issued = await _issue(stack, {"retrait": "ecriture"})
    secret, key_id = issued["secret"], issued["key"]["id"]

    regranted = await stack.admin.put(f"{ROUTE}/{key_id}/grants", json={"grants": []})
    emptied = _result(await _call(stack, "list_workspaces", bearer(secret)))
    revoked = await stack.admin.post(f"{ROUTE}/{key_id}/revoke")
    replay = await stack.admin.post(f"{ROUTE}/{key_id}/revoke")
    refused = await _call(stack, "list_workspaces", bearer(secret))
    after = await stack.admin.put(f"{ROUTE}/{key_id}/grants", json={"grants": []})

    assert regranted.json()["grants"] == [] and emptied == []
    assert revoked.json()["revoked_at"] is not None
    assert replay.headers["x-miles-already-exists"] == "true"
    assert replay.json()["revoked_at"] == revoked.json()["revoked_at"]
    assert refused.status_code == 401
    assert (after.status_code, after.json()["detail"]) == (409, "cle_revoquee")
    events = await stack.portal.pool.fetch(
        "SELECT type, author_directory, author_subject FROM events WHERE type LIKE 'api_key.%'"
        " ORDER BY written_at"
    )
    assert [(e["type"], e["author_subject"]) for e in events] == [
        ("api_key.issued", "admin"),
        ("api_key.grants_changed", "admin"),
        ("api_key.revoked", "admin"),
    ]


async def test_unknown_workspace_duplicate_grant_or_blank_label_issue_nothing(stack: Stack) -> None:
    unknown = await stack.admin.post(
        ROUTE, json={"label": "x", "grants": [{"workspace_id": "nulle-part", "access": "lecture"}]}
    )
    duplicate = await stack.admin.post(
        ROUTE,
        json={
            "label": "x",
            "grants": [
                {"workspace_id": "retrait", "access": "lecture"},
                {"workspace_id": "retrait", "access": "ecriture"},
            ],
        },
    )
    blank = await stack.admin.post(ROUTE, json={"label": "  ", "grants": []})
    bad_access = await stack.admin.post(
        ROUTE, json={"label": "x", "grants": [{"workspace_id": "retrait", "access": "admin"}]}
    )

    assert unknown.json()["detail"] == {
        "field": "grants",
        "reason": "workspace_inconnu",
        "workspace": "nulle-part",
    }
    assert duplicate.json()["detail"] == {"field": "grants", "reason": "workspace_en_double"}
    assert blank.json()["detail"] == {"field": "label", "reason": "vide"}
    assert bad_access.status_code == 422
    assert await stack.portal.pool.fetchval("SELECT count(*) FROM api_keys") == 0


async def test_last_use_is_recorded_at_most_once_a_minute(stack: Stack) -> None:
    secret = (await _issue(stack, {"retrait": "lecture"}))["secret"]

    await _call(stack, "list_workspaces", bearer(secret))
    first = await stack.portal.pool.fetchval("SELECT last_used_at FROM api_keys")
    await _call(stack, "list_workspaces", bearer(secret))
    second = await stack.portal.pool.fetchval("SELECT last_used_at FROM api_keys")
    await stack.portal.pool.execute(
        "UPDATE api_keys SET last_used_at = last_used_at - $1::interval", timedelta(minutes=2)
    )
    await _call(stack, "list_workspaces", bearer(secret))
    third = await stack.portal.pool.fetchval("SELECT last_used_at FROM api_keys")

    assert first is not None and second == first
    assert third > first - timedelta(minutes=2)


async def test_a_key_does_not_open_the_rest_routes_and_a_session_does_not_open_mcp(
    stack: Stack,
) -> None:
    secret = (await _issue(stack, {"retrait": "ecriture"}))["secret"]

    rest_by_key = await stack.mcp.get("/api/workspaces", headers=bearer(secret))
    mcp_by_session = await stack.admin.post(
        MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=ACCEPT
    )

    assert (rest_by_key.status_code, rest_by_key.json()["detail"]) == (401, "session_requise")
    assert mcp_by_session.status_code == 401
