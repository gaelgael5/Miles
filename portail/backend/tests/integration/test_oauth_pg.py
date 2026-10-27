from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.integration.oauth_helpers import (
    CALLBACK,
    PUBLIC,
    consent,
    declare_client,
    exchange,
    new_pkce,
    obtain_tokens,
    open_oauth,
    params,
    query_of,
)
from tests.integration.test_api_keys_pg import Stack, _call, _result, stack
from tests.integration.test_obo_pg import _oidc_client

pytestmark = pytest.mark.integration
__all__ = ["stack"]


@pytest.fixture
async def oauth(stack: Stack) -> AsyncIterator[Stack]:
    open_oauth(stack.portal)
    yield stack


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_metadata_tells_claude_where_to_get_a_token(oauth: Stack) -> None:
    resource = await oauth.mcp.get("/.well-known/oauth-protected-resource")
    server = await oauth.mcp.get("/.well-known/oauth-authorization-server")
    refused = await _call(oauth, "list_workspaces", {})

    assert resource.json()["resource"] == f"{PUBLIC}/mcp/"
    assert resource.json()["authorization_servers"] == [PUBLIC]
    assert server.json()["authorization_endpoint"] == f"{PUBLIC}/oauth/authorize"
    assert server.json()["code_challenge_methods_supported"] == ["S256"]
    assert server.json()["token_endpoint_auth_methods_supported"] == ["none"]
    metadata = f"{PUBLIC}/.well-known/oauth-protected-resource"
    assert refused.headers["www-authenticate"] == (
        f'Bearer realm="miles-mcp", resource_metadata="{metadata}"'
    )


async def test_without_public_url_oauth_announces_nothing(stack: Stack) -> None:
    resource = await stack.mcp.get("/.well-known/oauth-protected-resource")
    refused = await _call(stack, "list_workspaces", {})

    assert resource.status_code == 404
    assert "resource_metadata" not in refused.headers["www-authenticate"]


async def test_the_full_flow_opens_mcp_with_the_consented_rights_only(oauth: Stack) -> None:
    client_id = await declare_client(oauth.admin)
    pkce = new_pkce()
    shown = await oauth.admin.post("/api/oauth/authorize/check", json=params(client_id, pkce))
    approved = await consent(oauth.admin, client_id, pkce, {"retrait": "lecture"})
    redirect = query_of(approved.json()["redirect"])
    tokens = await exchange(oauth.mcp, client_id, redirect["code"], pkce.verifier)
    replay = await exchange(oauth.mcp, client_id, redirect["code"], pkce.verifier)
    seen = _result(await _call(oauth, "list_workspaces", bearer(tokens.json()["access_token"])))

    assert shown.json()["client"]["label"] == "claude.ai"
    assert {w["workspace_id"] for w in shown.json()["allowed"]} == {"retrait", "caisse", "stock"}
    assert approved.json()["redirect"].startswith(CALLBACK + "?")
    assert redirect["state"] == "etat-42"
    assert tokens.status_code == 200 and tokens.headers["cache-control"] == "no-store"
    assert tokens.json()["token_type"] == "Bearer" and tokens.json()["expires_in"] == 3600
    assert (replay.status_code, replay.json()["error"]) == (400, "invalid_grant")
    assert [(w["id"], w["access"]) for w in seen] == [("retrait", "lecture")]
    stored = await oauth.portal.pool.fetch("SELECT digest FROM oauth_tokens")
    assert all(tokens.json()["access_token"].encode() not in bytes(r["digest"]) for r in stored)


async def test_a_wrong_verifier_spends_the_code(oauth: Stack) -> None:
    client_id = await declare_client(oauth.admin)
    pkce = new_pkce()
    approved = await consent(oauth.admin, client_id, pkce, {})
    code = query_of(approved.json()["redirect"])["code"]

    wrong = await exchange(oauth.mcp, client_id, code, new_pkce().verifier)
    right = await exchange(oauth.mcp, client_id, code, pkce.verifier)

    assert wrong.json()["error"] == "invalid_grant"
    assert right.json()["error"] == "invalid_grant"


async def test_refresh_rotates_and_a_replay_revokes_the_whole_grant(oauth: Stack) -> None:
    client_id, first = await obtain_tokens(oauth.admin, oauth.mcp, {"retrait": "ecriture"})
    form = {"grant_type": "refresh_token", "client_id": client_id}

    second = await oauth.mcp.post(
        "/oauth/token", data=form | {"refresh_token": first["refresh_token"]}
    )
    replay = await oauth.mcp.post(
        "/oauth/token", data=form | {"refresh_token": first["refresh_token"]}
    )
    after = await _call(oauth, "list_workspaces", bearer(second.json()["access_token"]))
    again = await oauth.mcp.post(
        "/oauth/token", data=form | {"refresh_token": second.json()["refresh_token"]}
    )

    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    assert replay.json()["error"] == "invalid_grant"
    assert after.status_code == 401
    assert again.json()["error"] == "invalid_grant"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"client_id": "mcl_" + "0" * 32}, ("refus", "client_inconnu")),
        ({"redirect_uri": "https://ailleurs.invalid/cb"}, ("refus", "adresse_de_retour_inconnue")),
        ({"code_challenge_method": "plain"}, ("redirect", "invalid_request")),
        ({"response_type": "token"}, ("redirect", "unsupported_response_type")),
        ({"resource": "https://autre.invalid/mcp/"}, ("redirect", "invalid_target")),
    ],
)
async def test_bad_requests_are_refused_on_screen_or_sent_back_to_the_client(
    oauth: Stack, change: dict[str, str], expected: tuple[str, str]
) -> None:
    client_id = await declare_client(oauth.admin)
    asked = params(client_id, new_pkce()) | change

    checked = await oauth.admin.post("/api/oauth/authorize/check", json=asked)

    if expected[0] == "refus":
        assert (checked.status_code, checked.json()["detail"]) == (400, expected[1])
    else:
        sent = query_of(checked.json()["redirect"])
        assert checked.json()["redirect"].startswith(CALLBACK)
        assert (sent["error"], sent["state"]) == (expected[1], "etat-42")


async def test_a_person_without_rights_can_only_refuse(oauth: Stack) -> None:
    client_id = await declare_client(oauth.admin)
    pkce = new_pkce()
    async with await _oidc_client(oauth, "sub-lea", "Léa") as lea:
        shown = await lea.post("/api/oauth/authorize/check", json=params(client_id, pkce))
        excessive = await consent(lea, client_id, pkce, {"retrait": "lecture"})
        denied = await lea.post(
            "/api/oauth/authorize",
            json={"params": params(client_id, pkce), "decision": "deny", "grants": []},
        )

    assert shown.json()["allowed"] == []
    assert (excessive.status_code, excessive.json()["detail"]) == (400, "droit_excessif")
    assert query_of(denied.json()["redirect"])["error"] == "access_denied"


async def test_revoking_a_grant_or_deleting_the_client_closes_mcp(oauth: Stack) -> None:
    _, mine = await obtain_tokens(oauth.admin, oauth.mcp, {"retrait": "lecture"})
    client_id, other = await obtain_tokens(oauth.admin, oauth.mcp, {"caisse": "lecture"})
    listed = await oauth.admin.get("/api/auth/me/oauth-grants")
    first = listed.json()[0]["id"]

    revoked = await oauth.admin.delete(f"/api/auth/me/oauth-grants/{first}")
    after_revoke = await _call(oauth, "list_workspaces", bearer(mine["access_token"]))
    deleted = await oauth.admin.delete(f"/api/oauth-clients/{client_id}")
    after_delete = await _call(oauth, "list_workspaces", bearer(other["access_token"]))

    assert [g["grants"] for g in listed.json()] == [{"retrait": "lecture"}, {"caisse": "lecture"}]
    assert revoked.status_code == 204 and after_revoke.status_code == 401
    assert deleted.status_code == 204 and after_delete.status_code == 401


async def test_a_consent_stops_working_when_the_person_loses_their_rights(oauth: Stack) -> None:
    _, tokens = await obtain_tokens(oauth.admin, oauth.mcp, {"retrait": "lecture"})
    store = oauth.portal.app.state.auth.store
    account = store.account
    # Comme un compte d'amorçage retiré de .env : l'autorisation qu'il a donnée ne vaut plus.
    store._account = None
    try:
        refused = await _call(oauth, "list_workspaces", bearer(tokens["access_token"]))
    finally:
        store._account = account

    assert refused.status_code == 401


async def test_declaring_a_client_refuses_unsafe_return_addresses(oauth: Stack) -> None:
    refused = await oauth.admin.post(
        "/api/oauth-clients", json={"label": "x", "redirect_uris": ["http://claude.ai/cb"]}
    )
    endpoints = await oauth.admin.get("/api/oauth-clients/endpoints")

    assert refused.json()["detail"] == {"field": "redirect_uris"}
    assert endpoints.json()["mcp_url"] == f"{PUBLIC}/mcp/"
    assert endpoints.json()["suggested_redirect_uris"][0] == CALLBACK
