from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from miles.auth.sessions import SESSION_COOKIE
from miles.cultures.service import EVENT_TYPES as CULTURE_EVENTS
from miles.events.model import EventTypeCatalog
from miles.oidc.api_login import STATE_COOKIE
from miles.oidc.service import EVENT_TYPES as OIDC_EVENTS
from miles.oidc.service import OidcService
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

PUBLIC_URL = "http://miles.test"
CLIENT_ID = "miles-client"  # aud des jetons, configuré dans le mock par le script
CLIENT_SECRET = "secret-client-du-mock"


def _issuer() -> str:
    # Posé par scripts/run-integration-tests.sh, qui lance un vrai fournisseur OIDC
    # jetable (mock-oauth2-server) : c'est le parcours complet qu'on éprouve.
    base = os.environ.get("MILES_TEST_OIDC_URL")
    if not base:
        pytest.fail("MILES_TEST_OIDC_URL absent : lancer via scripts/run-integration-tests.sh")
    return f"{base}/miles"


@dataclass
class Flow:
    portal: PortalStack
    provider: httpx.AsyncClient

    @property
    def admin(self) -> httpx.AsyncClient:
        return self.portal.client


@pytest.fixture
async def flow(blank_db: str, tmp_path: Path) -> AsyncIterator[Flow]:
    catalog = EventTypeCatalog(SECRET_EVENTS | CULTURE_EVENTS | OIDC_EVENTS)
    async with open_portal_stack(blank_db, tmp_path) as portal, httpx.AsyncClient() as http:
        secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
        portal.app.state.secrets = secrets
        portal.app.state.oidc = OidcService(
            portal.pool, http, secrets, catalog, utc_now, PUBLIC_URL, allow_http_issuer=True
        )
        created = await portal.client.post(
            "/api/secrets",
            json={
                "slug": "mock-secret",
                "label": "Mock",
                "secret_type": "OIDC_CLIENT_SECRET",
                "value": CLIENT_SECRET,
            },
        )
        assert created.status_code == 201
        yield Flow(portal, http)


async def _declare(flow: Flow, connector_id: str = "mock", **overrides: object) -> httpx.Response:
    body = {
        "id": connector_id,
        "label": "Annuaire de test",
        "issuer": _issuer(),
        "client_id": CLIENT_ID,
        "client_secret_slug": "mock-secret",
    } | overrides
    return await flow.admin.post("/api/oidc/connectors", json=body)


async def _start(browser: httpx.AsyncClient, connector_id: str = "mock") -> httpx.Response:
    return await browser.get("/api/auth/oidc/start", params={"connector": connector_id})


async def _provider_redirect(flow: Flow, start: httpx.Response) -> dict[str, str]:
    """Ce que fait le navigateur chez le fournisseur : il en revient avec code et state."""
    assert start.status_code == 303
    back = await flow.provider.get(start.headers["location"])
    location = back.headers["location"]
    assert location.startswith(f"{PUBLIC_URL}/api/auth/oidc/callback?")
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


async def test_full_login_through_a_real_provider_opens_an_oidc_session(flow: Flow) -> None:
    assert (await _declare(flow)).status_code == 201
    async with flow.portal.anonymous() as browser:
        listed = await browser.get("/api/auth/oidc/connectors")
        start = await _start(browser)
        params = await _provider_redirect(flow, start)
        back = await browser.get("/api/auth/oidc/callback", params=params)
        me = await browser.get("/api/auth/me")
        forbidden = await browser.get("/api/secrets")

    assert listed.json() == [{"id": "mock", "label": "Annuaire de test"}]
    assert "SameSite=lax" in start.headers["set-cookie"]
    assert (back.status_code, back.headers["location"]) == (303, "/")
    assert SESSION_COOKIE in back.cookies
    assert me.json() == {
        "kind": "oidc",
        "username": "Alice",
        "email": "alice@example.org",
        "directory": "mock",
    }
    assert forbidden.status_code == 403
    identities = await flow.portal.pool.fetch("SELECT connector_id, subject FROM oidc_identities")
    assert [tuple(r) for r in identities] == [("mock", "alice-sub")]


async def test_replayed_callback_is_refused(flow: Flow) -> None:
    await _declare(flow)
    async with flow.portal.anonymous() as browser:
        params = await _provider_redirect(flow, await _start(browser))
        state = browser.cookies.get(STATE_COOKIE)
        assert (await browser.get("/api/auth/oidc/callback", params=params)).headers[
            "location"
        ] == "/"
        browser.cookies.set(STATE_COOKIE, state or "", path="/api/auth/oidc/callback")
        replay = await browser.get("/api/auth/oidc/callback", params=params)

    assert replay.headers["location"] == "/?login_error=state_invalide"


async def test_callback_from_another_browser_is_refused(flow: Flow) -> None:
    await _declare(flow)
    async with flow.portal.anonymous() as victim, flow.portal.anonymous() as attacker:
        params = await _provider_redirect(flow, await _start(attacker))
        # La victime suit le lien de retour de l'attaquant : elle n'a pas son cookie de state.
        forced = await victim.get("/api/auth/oidc/callback", params=params)
        me = await victim.get("/api/auth/me")

    assert forced.headers["location"] == "/?login_error=state_invalide"
    assert me.status_code == 401


async def test_missing_or_tampered_state_is_refused(flow: Flow) -> None:
    await _declare(flow)
    async with flow.portal.anonymous() as browser:
        params = await _provider_redirect(flow, await _start(browser))
        without = await browser.get("/api/auth/oidc/callback", params={"code": params["code"]})
        tampered = await browser.get(
            "/api/auth/oidc/callback", params={**params, "state": params["state"] + "x"}
        )

    for response in (without, tampered):
        assert response.headers["location"] == "/?login_error=state_invalide"
        assert SESSION_COOKIE not in response.cookies


async def test_provider_refusal_returns_to_login_without_session(flow: Flow) -> None:
    await _declare(flow)
    async with flow.portal.anonymous() as browser:
        start = await _start(browser)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        back = await browser.get(
            "/api/auth/oidc/callback", params={"state": state, "error": "access_denied"}
        )

    assert back.headers["location"] == "/?login_error=refus_fournisseur&connector=mock"
    assert SESSION_COOKIE not in back.cookies


async def test_inactive_connector_is_hidden_and_cannot_be_forced(flow: Flow) -> None:
    await _declare(flow, active=False)
    async with flow.portal.anonymous() as browser:
        listed = await browser.get("/api/auth/oidc/connectors")
        forced = await _start(browser)

    assert listed.json() == []
    assert forced.headers["location"] == "/?login_error=connecteur_inconnu"


async def test_two_connectors_coexist_on_the_login_screen(flow: Flow) -> None:
    await _declare(flow)
    await _declare(flow, "mock-bis", label="Autre annuaire")

    async with flow.portal.anonymous() as browser:
        listed = (await browser.get("/api/auth/oidc/connectors")).json()

    assert {c["id"] for c in listed} == {"mock", "mock-bis"}


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"issuer": "http://127.0.0.1:9/nowhere"}, {"field": "issuer", "reason": "injoignable"}),
        ({"client_id": " "}, {"field": "client_id"}),
        ({"client_secret_slug": "absent"}, {"field": "client_secret_slug"}),
        ({"scopes": "email"}, {"field": "scopes"}),
    ],
)
async def test_invalid_declaration_names_the_field_and_stores_nothing(
    flow: Flow, overrides: dict[str, object], detail: dict[str, str]
) -> None:
    response = await _declare(flow, **overrides)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert await flow.portal.pool.fetchval("SELECT count(*) FROM oidc_connectors") == 0


async def test_taken_identifier_is_refused(flow: Flow) -> None:
    await _declare(flow)

    again = await _declare(flow, label="Doublon")

    assert (again.status_code, again.json()["detail"]) == (409, "identifiant_pris")


async def test_client_secret_is_never_returned(flow: Flow) -> None:
    created = await _declare(flow)
    listed = await flow.admin.get("/api/oidc/connectors")

    for response in (created, listed):
        assert CLIENT_SECRET not in response.text
    assert listed.json()[0]["client_secret_slug"] == "mock-secret"


async def test_connector_used_for_login_cannot_be_deleted_only_deactivated(flow: Flow) -> None:
    await _declare(flow)
    async with flow.portal.anonymous() as browser:
        params = await _provider_redirect(flow, await _start(browser))
        await browser.get("/api/auth/oidc/callback", params=params)
        refused = await flow.admin.delete("/api/oidc/connectors/mock")
        body = {
            "label": "Annuaire de test",
            "issuer": _issuer(),
            "client_id": CLIENT_ID,
            "client_secret_slug": "mock-secret",
            "active": False,
        }
        deactivated = await flow.admin.put("/api/oidc/connectors/mock", json=body)
        # La session déjà ouverte survit au changement de configuration.
        still_in = await browser.get("/api/auth/me")

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "connecteur_utilise", "identities": 1}
    assert deactivated.json()["active"] is False
    assert still_in.status_code == 200


async def test_unused_connector_is_deleted_and_releases_its_secret(flow: Flow) -> None:
    await _declare(flow)
    in_use = await flow.admin.delete("/api/secrets/mock-secret")

    deleted = await flow.admin.delete("/api/oidc/connectors/mock")
    released = await flow.admin.delete("/api/secrets/mock-secret")

    assert in_use.status_code == 409
    assert in_use.json()["detail"]["consumers"] == [{"kind": "oidc.connector", "id": "mock"}]
    assert deleted.status_code == 204
    assert released.status_code == 204


async def test_connector_changes_are_journaled_with_their_author(flow: Flow) -> None:
    await _declare(flow)
    await flow.admin.delete("/api/oidc/connectors/mock")

    rows = await flow.portal.pool.fetch(
        "SELECT e.type, e.author_subject FROM events e JOIN event_objects o"
        " ON o.event_id = e.id WHERE o.object_kind = 'oidc_connector' ORDER BY o.sequence"
    )

    assert [tuple(r) for r in rows] == [
        ("oidc.connector.created", "admin"),
        ("oidc.connector.deleted", "admin"),
    ]


async def test_missing_public_url_makes_oidc_login_unavailable(flow: Flow) -> None:
    await _declare(flow)
    service: OidcService = flow.portal.app.state.oidc
    flow.portal.app.state.oidc = OidcService(
        service.pool, service.http, service.secrets, service.catalog, utc_now, None, True
    )
    async with flow.portal.anonymous() as browser:
        start = await _start(browser)

    assert start.headers["location"] == "/?login_error=url_publique_absente&connector=mock"
