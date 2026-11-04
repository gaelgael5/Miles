from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService

from miles.event_types import code_event_types
from miles.security.service import SecurityServices
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ROUTE = "/api/security-services"


def _env(name: str) -> str:
    # Posés par scripts/run-integration-tests.sh, qui lance un vrai Keycloak jetable
    # avec un realm « miles » et un client de compte de service.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} absent : lancer via scripts/run-integration-tests.sh")
    return value


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    catalog = EventTypeCatalog(code_event_types())
    async with open_portal_stack(blank_db, tmp_path) as portal, httpx.AsyncClient() as http:
        secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
        portal.app.state.secrets = secrets
        portal.app.state.security = SecurityServices(
            portal.pool, http, secrets, catalog, utc_now, allow_http=True
        )
        for slug, value in (("kc-bon", _env("MILES_TEST_KEYCLOAK_SECRET")), ("kc-faux", "faux")):
            created = await portal.client.post(
                "/api/secrets",
                json={
                    "slug": slug,
                    "label": slug,
                    "secret_type": "SECURITY_SERVICE_CLIENT_SECRET",
                    "value": value,
                },
            )
            assert created.status_code == 201
        yield portal


def _body(**overrides: str) -> dict[str, str]:
    return {
        "base_url": _env("MILES_TEST_KEYCLOAK_URL"),
        "realm": "miles",
        "client_id": "miles-backoffice",
        "client_secret_slug": "kc-bon",
    } | overrides


async def _declare(stack: PortalStack, **overrides: str) -> httpx.Response:
    return await stack.client.post(ROUTE, json={"id": "racine", **_body(**overrides)})


async def test_declared_service_is_verified_against_the_real_keycloak(stack: PortalStack) -> None:
    declared = await _declare(stack)

    assert declared.status_code == 201
    body = declared.json()
    assert (body["last_check_outcome"], body["dependent_installations"]) == ("ok", 0)
    assert body["client_secret_slug"] == "kc-bon"
    assert _env("MILES_TEST_KEYCLOAK_SECRET") not in declared.text


@pytest.mark.parametrize(
    ("overrides", "outcome"),
    [
        ({"realm": "inconnu"}, "realm_inconnu"),
        ({"client_secret_slug": "kc-faux"}, "refuse"),
        ({"client_id": "client-inconnu"}, "refuse"),
        ({"base_url": "http://127.0.0.1:9"}, "injoignable"),
    ],
)
async def test_verification_names_one_of_four_outcomes(
    stack: PortalStack, overrides: dict[str, str], outcome: str
) -> None:
    declared = await _declare(stack, **overrides)

    assert declared.status_code == 201
    assert declared.json()["last_check_outcome"] == outcome


async def test_only_one_root_service_can_be_declared(stack: PortalStack) -> None:
    await _declare(stack)

    second = await stack.client.post(ROUTE, json={"id": "autre", **_body()})

    assert (second.status_code, second.json()["detail"]) == (409, "service_deja_declare")


async def test_correcting_coordinates_reverifies_them(stack: PortalStack) -> None:
    await _declare(stack, client_secret_slug="kc-faux")

    corrected = await stack.client.put(f"{ROUTE}/racine", json=_body())
    usages = await stack.pool.fetch("SELECT secret_slug FROM secret_usages ORDER BY 1")

    assert corrected.json()["last_check_outcome"] == "ok"
    assert [r["secret_slug"] for r in usages] == ["kc-bon"]


async def test_explicit_verification_records_the_last_outcome(stack: PortalStack) -> None:
    await _declare(stack)
    await stack.pool.execute("UPDATE security_services SET realm = 'disparu'")

    checked = await stack.client.post(f"{ROUTE}/racine/verification")

    assert checked.json()["last_check_outcome"] == "realm_inconnu"
    assert checked.json()["last_check_at"] is not None


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"base_url": "ftp://x"}, "base_url"),
        ({"realm": "a/b"}, "realm"),
        ({"client_id": " "}, "client_id"),
        ({"client_secret_slug": "absent"}, "client_secret_slug"),
    ],
)
async def test_invalid_declaration_names_the_field_and_stores_nothing(
    stack: PortalStack, overrides: dict[str, str], field: str
) -> None:
    refused = await _declare(stack, **overrides)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": field})
    assert await stack.pool.fetchval("SELECT count(*) FROM security_services") == 0


async def test_used_secret_cannot_be_deleted(stack: PortalStack) -> None:
    await _declare(stack)

    refused = await stack.client.delete("/api/secrets/kc-bon")

    assert refused.json()["detail"]["consumers"] == [{"kind": "security_service", "id": "racine"}]


async def test_declaration_and_changes_are_journaled(stack: PortalStack) -> None:
    await _declare(stack)
    await stack.client.put(f"{ROUTE}/racine", json=_body(realm="miles"))

    types = await stack.pool.fetch(
        "SELECT e.type FROM events e JOIN event_objects o ON o.event_id = e.id"
        " WHERE o.object_kind = 'security_service' ORDER BY o.sequence"
    )

    assert [r["type"] for r in types] == ["security_service.declared", "security_service.updated"]


async def test_routes_require_the_administrator(stack: PortalStack) -> None:
    async with stack.anonymous() as anonymous:
        assert (await anonymous.get(ROUTE)).status_code == 401
        assert (await anonymous.post(ROUTE, json={"id": "x", **_body()})).status_code == 401
