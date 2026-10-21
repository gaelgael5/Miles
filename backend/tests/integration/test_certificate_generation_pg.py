from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.integration.git_stack import wire_git
from tests.integration.portal_stack import PortalStack, open_portal_stack

pytestmark = pytest.mark.integration

GENERATE = "/api/client-certificates/generate"


@pytest.fixture
async def portal(blank_db: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    # La génération ne touche aucune forge : la pile du portail suffit.
    async with open_portal_stack(blank_db, tmp_path) as stack:
        wire_git(stack, ("forge.example",))
        yield stack


async def _generate(portal: PortalStack, cid: str = "machine", days: int = 90) -> dict:
    body = {"id": cid, "label": "Machine de prod", "validity_days": days}
    response = await portal.client.post(GENERATE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_generated_certificate_is_listed_with_its_key_kept_as_a_used_secret(
    portal: PortalStack,
) -> None:
    created = await _generate(portal, days=90)

    expiry = datetime.fromisoformat(created["not_after"])
    assert timedelta(days=89) < expiry - datetime.now(UTC) <= timedelta(days=90)
    assert created["key_secret_slug"] == "machine-cle"
    assert created["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")
    listed = (await portal.client.get("/api/client-certificates")).json()
    assert [c["id"] for c in listed] == ["machine"]
    # Le certificat tient sa clé : le socle refuse de supprimer le secret.
    assert (await portal.client.delete("/api/secrets/machine-cle")).status_code == 409


async def test_generated_key_matches_its_certificate_for_a_connection(
    portal: PortalStack,
) -> None:
    await _generate(portal)
    body = {
        "id": "acme",
        "label": "Acme",
        "base_url": "https://forge.example/acme",
        "certificate_id": "machine",
    }

    created = await portal.client.post("/api/git-connections", json=body)

    assert created.status_code == 201, created.text


@pytest.mark.parametrize("days", [0, 3651], ids=["zero", "plus-de-dix-ans"])
async def test_validity_outside_one_to_3650_days_is_refused_naming_the_field(
    portal: PortalStack, days: int
) -> None:
    body = {"id": "machine", "label": "Machine", "validity_days": days}

    refused = await portal.client.post(GENERATE, json=body)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "validity_days"})
    assert await portal.pool.fetchval("SELECT count(*) FROM secrets") == 0


async def test_regenerating_under_a_taken_identifier_is_refused(portal: PortalStack) -> None:
    await _generate(portal)

    again = await portal.client.post(
        GENERATE, json={"id": "machine", "label": "Autre", "validity_days": 30}
    )

    assert (again.status_code, again.json()["detail"]) == (409, "identifiant_pris")


async def test_taken_identifier_found_after_the_key_is_written_leaves_no_orphan_key(
    portal: PortalStack,
) -> None:
    # Identifiant pris par un certificat dont la clé porte un autre slug : le refus vient
    # de l'insertion du certificat, après celle du secret, et doit défaire les deux.
    await _generate(portal, "autre")
    await portal.pool.execute("UPDATE client_certificates SET id = 'machine' WHERE id = 'autre'")

    again = await portal.client.post(
        GENERATE, json={"id": "machine", "label": "Autre", "validity_days": 30}
    )

    assert (again.status_code, again.json()["detail"]) == (409, "identifiant_pris")
    slugs = await portal.pool.fetch("SELECT slug FROM secrets ORDER BY slug")
    assert [r["slug"] for r in slugs] == ["autre-cle"]


async def test_key_slug_already_taken_by_a_secret_is_refused_without_certificate(
    portal: PortalStack,
) -> None:
    body = {"slug": "machine-cle", "label": "x", "secret_type": "GIT_TOKEN", "value": "v"}
    assert (await portal.client.post("/api/secrets", json=body)).status_code == 201

    refused = await portal.client.post(
        GENERATE, json={"id": "machine", "label": "Machine", "validity_days": 30}
    )

    assert (refused.status_code, refused.json()["detail"]) == (409, "cle_existante")
    assert await portal.pool.fetchval("SELECT count(*) FROM client_certificates") == 0


async def test_private_key_appears_in_no_response_and_no_event(portal: PortalStack) -> None:
    created = await _generate(portal)
    listed = await portal.client.get("/api/client-certificates")
    secret = await portal.client.get("/api/secrets/machine-cle")

    for text in (str(created), listed.text, secret.text):
        assert "PRIVATE KEY" not in text
    properties = await portal.pool.fetch("SELECT properties::text AS p FROM events")
    assert properties
    assert all("PRIVATE KEY" not in row["p"] for row in properties)
