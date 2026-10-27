from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from miles.cultures.service import EVENT_TYPES as CULTURE_EVENTS
from miles.cultures.service import CulturesService
from miles.events.model import EventTypeCatalog
from miles.oidc.service import EVENT_TYPES as OIDC_EVENTS
from miles.oidc.service import OidcService
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ROUTE = "/api/oidc/connectors"
# Long et non latin : affiché tel quel, sans troncature qui rendrait deux boutons identiques.
JAPANESE = "社内ディレクトリ" * 25


def _issuer() -> str:
    base = os.environ.get("MILES_TEST_OIDC_URL")
    if not base:
        pytest.fail("MILES_TEST_OIDC_URL absent : lancer via scripts/run-integration-tests.sh")
    return f"{base}/miles"


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    catalog = EventTypeCatalog(SECRET_EVENTS | CULTURE_EVENTS | OIDC_EVENTS)
    async with open_portal_stack(blank_db, tmp_path) as portal, httpx.AsyncClient() as http:
        secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
        portal.app.state.secrets = secrets
        portal.app.state.cultures = CulturesService(portal.pool, catalog, utc_now)
        portal.app.state.oidc = OidcService(
            portal.pool, http, secrets, catalog, utc_now, "http://miles.test", True
        )
        created = await portal.client.post(
            "/api/secrets",
            json={
                "slug": "kc-secret",
                "label": "kc",
                "secret_type": "OIDC_CLIENT_SECRET",
                "value": "v",
            },
        )
        assert created.status_code == 201
        await _activate(portal, "fr-FR", "ja-JP")
        yield portal


async def _activate(stack: PortalStack, *codes: str, active: bool = True) -> None:
    response = await stack.client.post(
        "/api/cultures/activation", json={"codes": list(codes), "active": active}
    )
    assert response.status_code == 200


def _body(labels: dict[str, str]) -> dict[str, object]:
    return {
        "labels": labels,
        "issuer": _issuer(),
        "client_id": "c",
        "client_secret_slug": "kc-secret",
    }


async def _declare(stack: PortalStack, labels: dict[str, str]) -> httpx.Response:
    return await stack.client.post(ROUTE, json={"id": "kc", **_body(labels)})


async def _declared(stack: PortalStack, labels: dict[str, str]) -> None:
    response = await _declare(stack, labels)
    assert response.status_code == 201, response.text


async def _shown(stack: PortalStack, culture: str | None) -> str:
    params = {} if culture is None else {"culture": culture}
    async with stack.anonymous() as visitor:
        listed = (await visitor.get("/api/auth/oidc/connectors", params=params)).json()
    return str(listed[0]["label"])


async def test_login_screen_shows_the_label_of_the_visitor_culture(stack: PortalStack) -> None:
    await _declared(stack, {"en-US": "Company directory", "fr-FR": "Annuaire maison"})

    assert await _shown(stack, "fr-FR") == "Annuaire maison"
    assert await _shown(stack, "en-US") == "Company directory"


@pytest.mark.parametrize("culture", ["ja-JP", "de-DE", "!!", "x" * 30, None])
async def test_every_other_case_falls_back_to_en_us(
    stack: PortalStack, culture: str | None
) -> None:
    # ja-JP active mais non renseignée ; de-DE inactive ; mal formée ; absente.
    await _declared(stack, {"en-US": "Company directory", "fr-FR": "Annuaire maison"})

    assert await _shown(stack, culture) == "Company directory"


async def test_en_us_label_is_mandatory(stack: PortalStack) -> None:
    refused = await _declare(stack, {"fr-FR": "Annuaire maison"})

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "label"})


async def test_labels_are_entered_only_for_active_cultures(stack: PortalStack) -> None:
    refused = await _declare(stack, {"en-US": "Directory", "de-DE": "Verzeichnis"})

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "labels"})
    assert await stack.pool.fetchval("SELECT count(*) FROM oidc_connectors") == 0


async def test_deactivated_culture_keeps_its_labels_and_gets_them_back(stack: PortalStack) -> None:
    await _declared(stack, {"en-US": "Company directory", "fr-FR": "Annuaire maison"})

    await _activate(stack, "fr-FR", active=False)
    hidden = await _shown(stack, "fr-FR")
    # L'administrateur réenregistre sans la culture désactivée : son libellé ne bouge pas.
    await stack.client.put(f"{ROUTE}/kc", json=_body({"en-US": "Company directory"}))
    kept = (await stack.client.get(ROUTE)).json()[0]["labels"]
    await _activate(stack, "fr-FR")

    assert hidden == "Company directory"
    assert kept == {"en-US": "Company directory", "fr-FR": "Annuaire maison"}
    assert await _shown(stack, "fr-FR") == "Annuaire maison"


async def test_culture_activated_later_is_completed_without_recreating(stack: PortalStack) -> None:
    await _declared(stack, {"en-US": "Company directory"})
    await _activate(stack, "de-DE")

    updated = await stack.client.put(
        f"{ROUTE}/kc", json=_body({"en-US": "Company directory", "de-DE": "Firmenverzeichnis"})
    )

    assert updated.status_code == 200
    assert await _shown(stack, "de-DE") == "Firmenverzeichnis"


async def test_empty_label_removes_it_and_the_change_is_journaled(stack: PortalStack) -> None:
    await _declared(stack, {"en-US": "Company directory", "fr-FR": "Annuaire maison"})

    await stack.client.put(f"{ROUTE}/kc", json=_body({"en-US": "Company directory", "fr-FR": ""}))

    assert (await stack.client.get(ROUTE)).json()[0]["labels"] == {"en-US": "Company directory"}
    changes = await stack.pool.fetchval(
        "SELECT properties->'changes'->'labels' FROM events WHERE type = 'oidc.connector.updated'"
    )
    assert json.loads(changes) == {
        "before": {"en-US": "Company directory", "fr-FR": "Annuaire maison"},
        "after": {"en-US": "Company directory"},
    }


async def test_long_non_latin_labels_are_kept_whole(stack: PortalStack) -> None:
    await _declared(stack, {"en-US": "Company directory", "ja-JP": JAPANESE})

    assert await _shown(stack, "ja-JP") == JAPANESE


async def test_login_screen_lists_active_cultures_without_session(stack: PortalStack) -> None:
    async with stack.anonymous() as visitor:
        cultures = (await visitor.get("/api/auth/cultures")).json()

    assert [c["code"] for c in cultures] == ["en-US", "fr-FR", "ja-JP"]
    assert cultures[1]["label_native"] == "français (France)"
