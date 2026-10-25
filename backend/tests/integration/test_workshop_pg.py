from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from miles.datamodels.schema import normalized
from tests.integration.test_datamodels_pg import PERSONNE, body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

VERSIONS = "/api/workspaces/retrait/versions"
MODELS = "/api/workspaces/retrait/data-models"
COLIS = normalized(
    "type: object\nproperties:\n  p:\n    $ref: miles:/shared/personne\n", "shared", "colis"
)


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _save(forge: Forge, label: str) -> httpx.Response:
    return await forge.client.post(VERSIONS, json={"label": label}, timeout=120)


async def _tags(forge: Forge) -> list[str]:
    listed = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/tags")
    return sorted(t["name"] for t in listed.json())


async def test_version_freezes_the_head_with_its_label_and_author(forge: Forge) -> None:
    await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)
    # Une version fige la tête publiée (9def0adc) : on publie d'abord.
    await forge.publish()
    head = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches/back/retrait/edition")

    saved = await _save(forge, "Recette du 21 octobre")
    listed = await forge.client.get(VERSIONS, timeout=120)

    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert (body["number"], body["label"]) == (1, "Recette du 21 octobre")
    assert body["commit"] == head.json()["commit"]["id"]
    # Sur une branche tenue, l'étiqueteur est la personne telle que la forge la connaît.
    assert body["author"] == await forge.identity()
    assert await _tags(forge) == ["version/1"]
    assert [(v["number"], v["commit"]) for v in listed.json()] == [(1, body["commit"])]
    event = await forge.portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = 'work_version.saved'"
    )
    assert event is not None


async def test_replay_is_without_effect_and_nothing_new_is_refused(forge: Forge) -> None:
    await _save(forge, "Initiale")

    replay = await _save(forge, "Initiale")
    nothing = await _save(forge, "Autre libellé")
    unlabeled = await _save(forge, "   ")

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (nothing.status_code, nothing.json()["detail"]) == (409, "rien_a_figer")
    assert unlabeled.json()["detail"] == {"field": "label"}
    assert await _tags(forge) == ["version/1"]


async def test_the_screen_can_ask_whether_anything_is_left_to_freeze(forge: Forge) -> None:
    """Gael, 25/10/2026 : le bouton se grise avant le clic, sur la réponse du serveur."""
    before = await forge.client.get(f"{VERSIONS}/freezable", timeout=120)
    await _save(forge, "Initiale")
    after = await forge.client.get(f"{VERSIONS}/freezable", timeout=120)

    assert before.json() == {"ok": True, "reason": None}
    # La même raison que le refus de l'enregistrement, calculée par le même code.
    assert after.json() == {"ok": False, "reason": "rien_a_figer"}


async def test_invalid_configuration_is_not_frozen_and_the_report_says_why(
    forge: Forge,
) -> None:
    # Écrit hors de Miles, directement sur la forge : un modèle qui désigne un absent.
    written = await forge.api.post(
        f"/api/v1/repos/miles/{forge.name}/contents/shared/messages/colis.yaml",
        json={
            "branch": "back/retrait/edition",
            "content": base64.b64encode(COLIS.encode()).decode(),
        },
    )
    assert written.status_code == 201, written.text

    refused = await _save(forge, "Ne doit pas passer")

    assert refused.status_code == 422
    assert refused.json()["detail"] == {
        "code": "parametrage_invalide",
        "reports": [
            {
                "path": "shared/messages/colis.yaml",
                "problems": [
                    {
                        "path": "properties.p.$ref",
                        "code": "modele_inconnu",
                        "detail": "shared/personne",
                    }
                ],
            }
        ],
    }
    assert await _tags(forge) == []


async def test_returning_to_a_version_adds_a_new_state(forge: Forge) -> None:
    await forge.client.post(MODELS, json=body_of(PERSONNE), timeout=120)
    await forge.publish()
    await _save(forge, "Avec personne")
    await forge.client.post(MODELS, json=body_of(COLIS), timeout=120)
    await forge.publish()
    await _save(forge, "Avec colis")
    before = await forge.commits()

    restored = await forge.client.post(f"{VERSIONS}/1/restore", timeout=120)
    again = await forge.client.post(f"{VERSIONS}/1/restore", timeout=120)
    unknown = await forge.client.post(f"{VERSIONS}/9/restore", timeout=120)

    assert restored.status_code == 200, restored.text
    assert await forge.commits() == before + 1
    assert await forge.file("domains/suivi/messages/colis.yaml") is None
    assert await forge.file("shared/messages/personne.yaml") == PERSONNE
    assert await _tags(forge) == ["version/1", "version/2"]
    assert (again.status_code, again.json()["detail"]) == (409, "deja_a_cette_version")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "version_inconnue")


async def test_unreachable_repository_designates_the_access(forge: Forge) -> None:
    assert (await forge.api.delete(f"/api/v1/repos/miles/{forge.name}")).status_code == 204

    refused = await _save(forge, "Trop tard")

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "acces_depot"
