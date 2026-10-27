from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.auth.api_preferences import PreferencesService
from miles.cultures.service import EVENT_TYPES as CULTURE_EVENTS
from miles.cultures.service import CulturesService
from miles.events.model import EventAuthor, EventTypeCatalog
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ROUTE = "/api/auth/me/preferences"


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    async with open_portal_stack(blank_db, tmp_path) as opened:
        cultures = CulturesService(opened.pool, EventTypeCatalog(CULTURE_EVENTS), utc_now)
        opened.app.state.cultures = cultures
        opened.app.state.preferences = PreferencesService(opened.pool, cultures, utc_now)
        yield opened


async def test_language_is_kept_for_the_account_and_only_an_active_culture_is_taken(
    stack: PortalStack,
) -> None:
    before = await stack.client.get(ROUTE)
    inactive = await stack.client.put(ROUTE, json={"language": "fr-FR"})
    await stack.client.post("/api/cultures/activation", json={"codes": ["fr-FR"], "active": True})
    chosen = await stack.client.put(ROUTE, json={"language": "fr-FR"})
    unknown = await stack.client.put(ROUTE, json={"language": "xx-YY"})
    after = await stack.client.get(ROUTE)

    assert before.json() == {"language": None}
    assert (inactive.status_code, inactive.json()["detail"]) == (422, {"field": "language"})
    assert chosen.json() == {"language": "fr-FR"}
    assert unknown.status_code == 422
    assert after.json() == {"language": "fr-FR"}


async def test_each_account_has_its_own_language(stack: PortalStack) -> None:
    service: PreferencesService = stack.app.state.preferences
    bob = EventAuthor("annuaire-x", "bob")

    await service.resolve_set_language(bob, "en-US")
    mine = await stack.client.get(ROUTE)

    assert mine.json() == {"language": None}
    assert await service.resolve_language(bob) == "en-US"
