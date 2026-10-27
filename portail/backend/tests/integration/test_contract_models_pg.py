from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml

from tests.integration.test_contracts_pg import ROUTE, _declare, _import
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

# Modèles dérivés d'une version de contrat (story 47f55d8b) : un par schéma, sous le
# contrat, dans le commit de la version.
MATERIEL = """openapi: 3.0.3
info: {title: Matériel, version: "1"}
paths:
  /points:
    get:
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/PickupPoint"}
components:
  schemas:
    PickupPoint:
      type: object
      properties:
        statut: {$ref: "#/components/schemas/Statut"}
        nom: {type: string, nullable: true}
    Statut: {type: string, enum: [ouvert, ferme]}
"""
MODELS = "contracts/suivi/models/v1"
VERSIONS = "/api/workspaces/retrait/versions"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _outside(forge: Forge, path: str, content: str | None) -> None:
    """Retouche de la branche directement sur la forge, hors de Miles."""
    url = f"/api/v1/repos/miles/{forge.name}/contents/{path}"
    current = await forge.api.get(url, params={"ref": "back/retrait/edition"})
    body = {"branch": "back/retrait/edition", "sha": current.json()["sha"]}
    if content is None:
        done = await forge.api.request("DELETE", url, json=body)
    else:
        encoded = base64.b64encode(content.encode()).decode()
        done = await forge.api.put(url, json=body | {"content": encoded})
    assert done.status_code in (200, 204), done.text


async def test_integrating_a_version_writes_one_model_per_schema_in_the_same_commit(
    forge: Forge,
) -> None:
    await _declare(forge)
    preview = await forge.client.post(f"{ROUTE}/preview", json={"content": MATERIEL})
    before = await forge.commits()

    imported = await _import(forge, MATERIEL)
    point = await forge.client.get(f"{ROUTE}/suivi/versions/1/models/pickup-point", timeout=120)
    missing = await forge.client.get(f"{ROUTE}/suivi/versions/1/models/absent", timeout=120)
    traversal = await forge.client.get(f"{ROUTE}/suivi/versions/1/models/..%2Fv1", timeout=120)

    assert preview.json()["models"] == ["pickup-point", "statut"]
    assert imported.status_code == 201, imported.text
    assert (imported.json()["models"], imported.json()["models_state"]) == (
        ["pickup-point", "statut"],
        "a_jour",
    )
    assert await forge.commits() == before + 1
    schema = yaml.safe_load(await forge.file(f"{MODELS}/pickup-point.yaml") or "")
    assert schema["$id"] == "miles:/contracts/suivi/v1/pickup-point"
    assert schema["properties"] == {
        "statut": {"$ref": "miles:/contracts/suivi/v1/statut"},
        "nom": {"type": ["string", "null"]},
    }
    assert point.json()["path"] == f"{MODELS}/pickup-point.yaml"
    assert yaml.safe_load(point.json()["content"]) == schema
    assert (missing.status_code, missing.json()["detail"]) == (404, "contrat_inconnu")
    assert traversal.status_code in (404, 422)


async def test_an_underivable_contract_is_refused_with_its_schemas_named(forge: Forge) -> None:
    await _declare(forge)
    clash = MATERIEL + "    statut: {type: string}\n"
    before = await forge.commits()

    preview = await forge.client.post(f"{ROUTE}/preview", json={"content": clash})
    refused = await _import(forge, clash)

    for response in (preview, refused):
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == {
            "code": "derivation_impossible",
            "problems": [
                {
                    "path": "components.schemas.statut",
                    "code": "noms_de_schema_en_collision",
                    "detail": "Statut",
                }
            ],
        }
    assert await forge.commits() == before
    assert await forge.file("contracts/suivi/v1.yaml") is None


async def test_tampered_models_block_a_version_until_they_are_rederived(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, MATERIEL)
    await forge.publish()
    await _outside(forge, f"{MODELS}/statut.yaml", "type: integer\n")
    await _outside(forge, f"{MODELS}/pickup-point.yaml", None)

    detail = await forge.client.get(f"{ROUTE}/suivi", timeout=120)
    blocked = await forge.client.post(VERSIONS, json={"label": "Retouché"}, timeout=120)
    rederived = await forge.client.post(f"{ROUTE}/suivi/versions/1/models", timeout=120)
    again = await forge.client.post(f"{ROUTE}/suivi/versions/1/models", timeout=120)
    await forge.publish()
    saved = await forge.client.post(VERSIONS, json={"label": "Redérivé"}, timeout=120)

    assert detail.json()["versions"][0]["models_state"] == "a_rederiver"
    assert blocked.json()["detail"]["reports"] == [
        {
            "path": "contracts/suivi/v1.yaml",
            "problems": [
                {"path": "models", "code": "modeles_derives_desynchronises", "detail": None}
            ],
        }
    ]
    assert rederived.status_code == 200, rederived.text
    assert rederived.json()["models_state"] == "a_jour"
    assert again.headers["x-miles-already-exists"] == "true"
    assert yaml.safe_load(await forge.file(f"{MODELS}/statut.yaml") or "")["type"] == "string"
    assert await forge.file(f"{MODELS}/pickup-point.yaml") is not None
    assert saved.status_code == 201, saved.text
    events = await forge.portal.pool.fetch(
        "SELECT 1 FROM events WHERE type = 'contract.models_rederived'"
    )
    assert len(events) == 1


async def test_deleting_a_contract_removes_its_derived_models(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, MATERIEL)

    deleted = await forge.client.delete(f"{ROUTE}/suivi", timeout=120)

    assert deleted.status_code == 204, deleted.text
    assert await forge.file(f"{MODELS}/pickup-point.yaml") is None
    assert await forge.file(f"{MODELS}/statut.yaml") is None


async def test_the_root_branch_reads_derived_models_but_cannot_rederive(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, MATERIEL)

    refused = await forge.client.post(
        f"{ROUTE}/suivi/versions/1/models", params={"branch": "atelier"}, timeout=120
    )

    assert (refused.status_code, refused.json()["detail"]) == (409, "branche_racine_lecture_seule")
