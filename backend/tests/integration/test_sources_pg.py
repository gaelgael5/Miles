from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from miles.datamodels.schema import normalized
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/sources"
MODELS = "/api/workspaces/retrait/data-models"
CHAINS = "/api/workspaces/retrait/transformations"
ADRESSE = normalized("type: object\nproperties:\n  ville:\n    type: string\n", "shared", "adresse")
COMPTE = normalized(
    "type: object\nproperties:\n  code:\n    type: string\n"
    "  adresse:\n    $ref: miles:/shared/adresse\n"
    "  enseignes:\n    type: array\n    items:\n      type: string\n",
    "shared",
    "compte",
)
SOURCE: dict[str, Any] = {
    "name": "comptes",
    "model": "shared/compte",
    "split": "$.accounts[*]",
    "keys": ["$.accountId"],
    "chain": "comptes-import",
    "large_file": True,
    "unified_transaction": False,
    "filterables": [
        {"name": "code", "jpath": "$.code"},
        {"name": "ville", "jpath": "$.adresse.ville"},
    ],
}


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        for model in (ADRESSE, COMPTE):
            created = await opened.client.post(MODELS, json=body_of(model), timeout=120)
            assert created.status_code == 201, created.text
        chain = {"label": "Import", "steps": [{"name": "copier", "template": '{ "code": $.code }'}]}
        saved = await opened.client.put(f"{CHAINS}/comptes-import", json=chain, timeout=120)
        assert saved.status_code == 200, saved.text
        yield opened


async def _declare(forge: Forge, **changes: Any) -> httpx.Response:
    return await forge.client.post(ROUTE, json=SOURCE | changes, timeout=120)


async def test_source_is_declared_in_git_and_designates_its_chain(forge: Forge) -> None:
    declared = await _declare(forge)
    read = await forge.client.get(f"{ROUTE}/comptes", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert declared.status_code == 201, declared.text
    assert declared.json() == SOURCE | {"rewrite_announced": False}
    assert read.json() == SOURCE
    assert listed.json() == [
        {"name": "comptes", "model": "shared/compte", "chain": "comptes-import"}
    ]
    text = await forge.file("sources/comptes.yaml")
    assert text is not None and 'chaine: "comptes-import"' in text


async def test_everything_the_branch_must_provide_is_checked_and_reported(forge: Forge) -> None:
    before = await forge.commits()

    refused = await _declare(
        forge,
        model="shared/inconnu",
        chain="absente",
        split="$.accounts[?(@.a == 1)]",
        keys=[],
    )
    filters = await _declare(
        forge,
        filterables=[
            {"name": "enseignes", "jpath": "$.enseignes"},
            {"name": "adresse", "jpath": "$.adresse"},
            {"name": "rien", "jpath": "$.rien"},
        ],
    )

    assert {(p["path"], p["code"]) for p in refused.json()["detail"]["problems"]} == {
        ("decoupage", "non_streamable"),
        ("cle", "cle_vide"),
    }
    assert {(p["path"], p["code"]) for p in filters.json()["detail"]["problems"]} == {
        ("filtrables[0].jpath", "tableau_interdit"),
        ("filtrables[1].jpath", "valeur_attendue"),
        ("filtrables[2].jpath", "propriete_inconnue"),
    }
    unknown = await _declare(forge, model="shared/inconnu", chain="absente")
    assert {(p["path"], p["code"]) for p in unknown.json()["detail"]["problems"]} == {
        ("modele", "modele_inconnu"),
        ("chaine", "chaine_inconnue"),
    }
    assert await forge.commits() == before


async def test_replay_name_taken_and_modification_that_announces_a_rewrite(forge: Forge) -> None:
    await _declare(forge)
    before = await forge.commits()

    replay = await _declare(forge)
    taken = await _declare(forge, large_file=False)
    same_chain = await forge.client.put(
        f"{ROUTE}/comptes", json=SOURCE | {"large_file": False}, timeout=120
    )
    new_filters = await forge.client.put(
        f"{ROUTE}/comptes", json=SOURCE | {"large_file": False, "filterables": []}, timeout=120
    )
    renamed = await forge.client.put(f"{ROUTE}/autre", json=SOURCE, timeout=120)

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (taken.status_code, taken.json()["detail"]) == (409, "nom_pris")
    assert same_chain.json()["rewrite_announced"] is False
    assert new_filters.json()["rewrite_announced"] is True
    assert (renamed.status_code, renamed.json()["detail"]) == (409, "nom_fige")
    assert await forge.commits() == before + 2


async def test_a_chain_designated_by_a_source_cannot_be_deleted(forge: Forge) -> None:
    await _declare(forge)

    refused = await forge.client.delete(f"{CHAINS}/comptes-import", timeout=120)
    await forge.client.delete(f"{ROUTE}/comptes", timeout=120)
    allowed = await forge.client.delete(f"{CHAINS}/comptes-import", timeout=120)

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        {"code": "chaine_utilisee", "by": ["comptes"]},
    )
    assert allowed.status_code == 204


async def test_a_version_cannot_freeze_a_source_broken_outside_miles(forge: Forge) -> None:
    await _declare(forge)
    await forge.publish()
    path = "sources/comptes.yaml"
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}", params={"ref": "work/edition"}
    )
    text = (await forge.file(path) or "").replace("$.accounts[*]", "$..accounts[*]")
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}",
        json={
            "branch": "work/edition",
            "sha": meta.json()["sha"],
            "content": base64.b64encode(text.encode()).decode(),
        },
    )
    assert changed.status_code == 200, changed.text

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Source cassée"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": path,
            "problems": [
                {
                    "path": "decoupage",
                    "code": "non_streamable",
                    "detail": "descente « .. » non bornée",
                }
            ],
        }
    ]
