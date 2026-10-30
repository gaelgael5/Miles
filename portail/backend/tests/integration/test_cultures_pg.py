from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from miles_socle.cultures.service import CulturesService
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.events.model import EventTypeCatalog

from miles.config import DEFAULT_MIGRATIONS_DIR
from miles.event_types import code_event_types
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ACTIVATION = "/api/cultures/activation"


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    async with open_portal_stack(blank_db, tmp_path) as portal:
        portal.app.state.cultures = CulturesService(
            portal.pool, EventTypeCatalog(code_event_types()), utc_now
        )
        yield portal


async def _active(stack: PortalStack) -> list[str]:
    response = await stack.client.get("/api/cultures/active")
    return [c["code"] for c in response.json()]


async def test_new_installation_has_the_full_list_with_only_en_us_active(
    stack: PortalStack,
) -> None:
    every = (await stack.client.get("/api/cultures")).json()

    assert len(every) > 700
    assert await _active(stack) == ["en-US"]
    french = next(c for c in every if c["code"] == "fr-FR")
    assert french == {
        "code": "fr-FR",
        "label_en": "French (France)",
        "label_native": "français (France)",
        "active": False,
    }


async def test_activation_applies_exactly_the_selection_and_is_replayable(
    stack: PortalStack,
) -> None:
    first = await stack.client.post(ACTIVATION, json={"codes": ["fr-FR", "de-DE"], "active": True})
    replay = await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})

    assert first.json() == {"changed": ["de-DE", "fr-FR"]}
    assert replay.status_code == 200 and replay.json() == {"changed": []}
    assert await _active(stack) == ["de-DE", "en-US", "fr-FR"]


async def test_deactivation_stops_serving_and_reactivation_restores(stack: PortalStack) -> None:
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})

    off = await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": False})
    assert off.json() == {"changed": ["fr-FR"]}
    assert await _active(stack) == ["en-US"]
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})
    assert await _active(stack) == ["en-US", "fr-FR"]


async def test_en_us_cannot_be_deactivated_and_nothing_else_changes(stack: PortalStack) -> None:
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})

    refused = await stack.client.post(
        ACTIVATION, json={"codes": ["fr-FR", "en-US"], "active": False}
    )

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "repli_obligatoire"}
    assert await _active(stack) == ["en-US", "fr-FR"]


async def test_database_itself_refuses_deactivating_en_us(stack: PortalStack) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await stack.pool.execute("UPDATE cultures SET active = false WHERE code = 'en-US'")


@pytest.mark.parametrize(
    ("codes", "detail"),
    [
        (["fr-FR", "xx-YY"], {"field": "codes", "unknown": ["xx-YY"]}),
        ([], {"field": "codes"}),
    ],
)
async def test_unknown_or_empty_selection_is_refused_without_partial_change(
    stack: PortalStack, codes: list[str], detail: dict[str, object]
) -> None:
    response = await stack.client.post(ACTIVATION, json={"codes": codes, "active": True})

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert await _active(stack) == ["en-US"]


async def test_each_real_change_writes_one_event_naming_the_changed_cultures(
    stack: PortalStack,
) -> None:
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR", "de-DE"], "active": True})
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})  # rejeu
    await stack.client.post(ACTIVATION, json={"codes": ["de-DE"], "active": False})

    rows = await stack.pool.fetch(
        "SELECT e.type, array_agg(o.object_id ORDER BY o.object_id) AS ids FROM events e"
        " JOIN event_objects o ON o.event_id = e.id GROUP BY e.id, e.type, e.written_at"
        " ORDER BY e.written_at"
    )
    assert [(r["type"], r["ids"]) for r in rows] == [
        ("culture.activated", ["de-DE", "fr-FR"]),
        ("culture.deactivated", ["de-DE"]),
    ]


async def test_culture_routes_require_a_session(stack: PortalStack) -> None:
    async with stack.anonymous() as anonymous:
        assert (await anonymous.get("/api/cultures")).status_code == 401
        assert (await anonymous.get("/api/cultures/active")).status_code == 401
        refused = await anonymous.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})
        assert refused.status_code == 401
    assert await _active(stack) == ["en-US"]


async def test_migration_replays_on_an_existing_base_without_touching_active_state(
    stack: PortalStack,
) -> None:
    await stack.client.post(ACTIVATION, json={"codes": ["fr-FR"], "active": True})

    async with stack.pool.acquire() as conn:
        applied = await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))

    assert applied == []
    assert await _active(stack) == ["en-US", "fr-FR"]
