from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from miles.datamodels.schema import normalized
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/sources"
STORAGES = "/api/workspaces/retrait/storages"
MODELS = "/api/workspaces/retrait/data-models"
CHAINS = "/api/workspaces/retrait/transformations"
COMPTE = normalized("type: object\nproperties:\n  code:\n    type: string\n", "shared", "compte")
# Le modèle de CE QU'ON REÇOIT. Son nom porte un tiret à dessein — « pudo/import-crm » en
# porte un, et le motif de référence le refusait.
BRUT = normalized(
    "type: object\nproperties:\n  accountId:\n    type: string\n", "shared", "compte-brut"
)
STORAGE: dict[str, Any] = {
    "name": "comptes",
    "label": "Comptes",
    "model": "shared/compte",
    "keys": ["$.code"],
    "indexes": [],
}
# Refondue le 25/10/2026 : la source dit OÙ ça va (la donnée cible) et porte ses entrées.
ENTRY: dict[str, Any] = {
    "kind": "web",
    "source_model": "shared/compte-brut",
    "chain": "comptes-import",
    "modes": {"element": True, "batch": True, "file": True},
    "split": "$.accounts[*]",
    "unified_transaction": False,
    "write_batch": 1,
}
SOURCE: dict[str, Any] = {
    "name": "comptes",
    "label": "Comptes",
    "storage": "comptes",
    "entries": [ENTRY],
}


def with_entry(**changes: Any) -> dict[str, Any]:
    """La source, dont l'unique entrée porte ces changements."""
    body = deepcopy(SOURCE)
    body["entries"][0].update(changes)
    return body


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        for model in (COMPTE, BRUT):
            created = await opened.client.post(MODELS, json=body_of(model), timeout=120)
            assert created.status_code == 201, created.text
        for slug in ("comptes-import", "autre-import"):
            chain = {
                "label": "Import",
                "steps": [{"name": "copier", "template": '{ "code": $.code }'}],
            }
            saved = await opened.client.put(f"{CHAINS}/{slug}", json=chain, timeout=120)
            assert saved.status_code == 200, saved.text
        declared = await opened.client.post(STORAGES, json=STORAGE, timeout=120)
        assert declared.status_code == 201, declared.text
        yield opened


async def _declare(forge: Forge, body: dict[str, Any] | None = None, **changes: Any):
    return await forge.client.post(ROUTE, json=(body or SOURCE) | changes, timeout=120)


async def test_the_target_data_alone_is_enough_to_save(forge: Forge) -> None:
    """Gael, 25/10/2026 : libellé, slug, donnée cible — « la fenêtre peut être enregistrée »."""
    bare = {"name": "vide", "label": "Vide", "storage": "comptes", "entries": []}

    declared = await forge.client.post(ROUTE, json=bare, timeout=120)

    assert declared.status_code == 201, declared.text
    assert declared.json() == bare | {"rewrite_announced": False}


async def test_a_source_is_declared_in_git_with_its_entry(forge: Forge) -> None:
    declared = await _declare(forge)
    read = await forge.client.get(f"{ROUTE}/comptes", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert declared.status_code == 201, declared.text
    assert read.json() == SOURCE
    assert listed.json() == [
        {"name": "comptes", "label": "Comptes", "storage": "comptes", "entries": 1}
    ]
    text = await forge.file("sources/comptes.yaml")
    assert text is not None
    assert 'storage: "comptes"' in text and 'modele_source: "shared/compte-brut"' in text
    assert "element: true" in text and "fichier: true" in text


async def test_everything_each_entry_needs_is_checked_and_named_by_rank(forge: Forge) -> None:
    before = await forge.commits()

    unknown = await _declare(
        forge, with_entry(source_model="shared/inconnu", chain="absente"), storage="absent"
    )
    mute = await _declare(
        forge, with_entry(modes={"element": False, "batch": False, "file": False})
    )

    assert {(p["path"], p["code"]) for p in unknown.json()["detail"]["problems"]} == {
        ("storage", "storage_inconnu"),
        ("entrees[0].modele_source", "modele_inconnu"),
        ("entrees[0].chaine", "chaine_inconnue"),
    }
    assert ("entrees[0].modes", "aucun_mode") in {
        (p["path"], p["code"]) for p in mute.json()["detail"]["problems"]
    }
    assert await forge.commits() == before


async def test_the_split_is_required_by_the_file_mode_and_by_it_alone(forge: Forge) -> None:
    streamed = await _declare(
        forge, with_entry(modes={"element": False, "batch": False, "file": True}, split="")
    )
    typed = await _declare(
        forge, with_entry(modes={"element": True, "batch": True, "file": False}, split="")
    )

    assert [(p["path"], p["code"]) for p in streamed.json()["detail"]["problems"]] == [
        ("entrees[0].decoupage", "decoupage_absent")
    ]
    assert typed.status_code == 201, typed.text


async def test_a_chain_that_starts_or_ends_elsewhere_is_refused_by_name(forge: Forge) -> None:
    """Gael, 25/10/2026 : la chaîne part du modèle source et arrive au modèle du storage."""
    chain = {
        "label": "Ailleurs",
        "steps": [
            {
                "name": "copier",
                "template": '{ "code": $.code }',
                "source_model": "miles:/shared/compte",
                "destination_model": "miles:/shared/compte-brut",
            }
        ],
    }
    saved = await forge.client.put(f"{CHAINS}/ailleurs", json=chain, timeout=120)
    assert saved.status_code == 200, saved.text

    refused = await _declare(forge, with_entry(chain="ailleurs"))

    assert {(p["path"], p["code"]) for p in refused.json()["detail"]["problems"]} == {
        ("entrees[0].chaine", "chaine_part_d_ailleurs"),
        ("entrees[0].chaine", "chaine_arrive_ailleurs"),
    }


async def test_a_chain_whose_endpoints_match_is_accepted(forge: Forge) -> None:
    """Une chaîne qui déclare les bons modèles passe : la garde ne mord que sur l'écart."""
    chain = {
        "label": "Juste",
        "steps": [
            {
                "name": "copier",
                "template": '{ "code": $.accountId }',
                "source_model": "miles:/shared/compte-brut",
                "destination_model": "miles:/shared/compte",
            }
        ],
    }
    await forge.client.put(f"{CHAINS}/juste", json=chain, timeout=120)

    declared = await _declare(forge, with_entry(chain="juste"))

    assert declared.status_code == 201, declared.text


async def test_replay_name_taken_and_a_changed_entry_announcing_a_rewrite(forge: Forge) -> None:
    await _declare(forge)
    before = await forge.commits()

    replay = await _declare(forge)
    taken = await _declare(forge, with_entry(chain="autre-import"))
    same = await forge.client.put(f"{ROUTE}/comptes", json=SOURCE, timeout=120)
    changed = await forge.client.put(
        f"{ROUTE}/comptes", json=with_entry(chain="autre-import"), timeout=120
    )
    renamed = await forge.client.put(f"{ROUTE}/autre", json=SOURCE, timeout=120)

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (taken.status_code, taken.json()["detail"]) == (409, "nom_pris")
    assert (same.status_code, same.headers["x-miles-already-exists"]) == (200, "true")
    assert changed.json()["rewrite_announced"] is True
    assert (renamed.status_code, renamed.json()["detail"]) == (409, "nom_fige")
    assert await forge.commits() == before + 1


async def test_the_write_batch_is_declared_and_refused_below_one(forge: Forge) -> None:
    """Gael, 25/10/2026 : combien de lectures consécutives avant enregistrement."""
    declared = await _declare(forge, with_entry(write_batch=500, unified_transaction=True))
    refused = await _declare(forge, with_entry(write_batch=0), name="zero")

    assert declared.status_code == 201, declared.text
    text = await forge.file("sources/comptes.yaml")
    assert text is not None and "lot_ecriture: 500" in text
    # Le plancher est tenu par le contrat d'entrée : 422 avant la validation métier.
    assert refused.status_code == 422, refused.text


async def test_a_chain_designated_by_an_entry_cannot_be_deleted(forge: Forge) -> None:
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
        f"/api/v1/repos/miles/{forge.name}/contents/{path}", params={"ref": "back/retrait/edition"}
    )
    text = (await forge.file(path) or "").replace("$.accounts[*]", "$..accounts[*]")
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}",
        json={
            "branch": "back/retrait/edition",
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
                    "path": "entrees[0].decoupage",
                    "code": "non_streamable",
                    "detail": "descente « .. » non bornée",
                }
            ],
        }
    ]
