from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from miles.datamodels.schema import normalized
from tests.integration.mcp_stack import McpForge, open_mcp_forge
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import ROOT, Forge, open_work_forge

pytestmark = pytest.mark.integration

REFERENCE = "/api/workspaces/retrait/account-reference"
STORAGES = "/api/workspaces/retrait/storages"
MODELS = "/api/workspaces/retrait/data-models"
EDIT = {"workspace_id": "retrait", "branch": "edition"}

COMPTE = normalized(
    "type: object\nproperties:\n  identifiant:\n    type: string\n  telephone:\n    type: string\n",
    "shared",
    "compte",
)
SITE = normalized("type: object\nproperties:\n  code:\n    type: string\n", "shared", "site")
COMPTES: dict[str, Any] = {
    "name": "comptes",
    "label": "Comptes",
    "model": "shared/compte",
    "keys": ["$.identifiant"],
    "indexes": [],
}
SITES: dict[str, Any] = {
    "name": "sites",
    "label": "Sites",
    "model": "shared/site",
    "keys": ["$.code"],
    "indexes": [],
}


async def _stocked(forge: Forge) -> None:
    for model in (COMPTE, SITE):
        created = await forge.client.post(MODELS, json=body_of(model), timeout=120)
        assert created.status_code == 201, created.text
    for storage in (COMPTES, SITES):
        declared = await forge.client.post(STORAGES, json=storage, timeout=120)
        assert declared.status_code == 201, declared.text


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        await _stocked(opened)
        yield opened


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        await _stocked(opened.forge)
        yield opened


async def test_a_branch_without_a_reference_is_not_an_error(forge: Forge) -> None:
    """Critère 6 : rien n'est déclaré, et ça se dit autrement qu'un défaut."""
    read = await forge.client.get(REFERENCE, timeout=120)

    assert read.status_code == 200, read.text
    assert read.json() == {"storage": None, "model": None, "problem": None}


async def test_the_storage_is_designated_and_its_model_comes_back_read_from_it(
    forge: Forge,
) -> None:
    """Critère 1 : une seule liste. Le modèle n'est pas choisi, il est LU dans le storage."""
    set_up = await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    read = await forge.client.get(REFERENCE, timeout=120)

    assert set_up.status_code == 200, set_up.text
    assert set_up.json() == {"storage": "comptes", "model": "shared/compte", "problem": None}
    assert read.json() == set_up.json()
    # Et dans le dépôt : le storage, et RIEN d'autre. Le modèle n'y est pas écrit, sans
    # quoi il dériverait le jour où le storage change de modèle.
    text = await forge.file("comptes/reference.yaml")
    assert text == 'storage: "comptes"\n'


async def test_the_model_follows_the_storage_without_rewriting_the_reference(
    forge: Forge,
) -> None:
    """La conséquence qu'on a voulue : changer le modèle du storage change la référence.

    C'est la raison pour laquelle le modèle n'est pas recopié dans le fichier. S'il
    l'était, ce test montrerait l'ancien modèle et personne ne le saurait.
    """
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    moved = await forge.client.put(
        f"{STORAGES}/comptes",
        json=COMPTES | {"model": "shared/site", "keys": ["$.code"]},
        timeout=120,
    )
    read = await forge.client.get(REFERENCE, timeout=120)

    assert moved.status_code == 200, moved.text
    assert read.json() == {"storage": "comptes", "model": "shared/site", "problem": None}


async def test_an_unknown_storage_is_refused_and_the_refusal_names_those_that_exist(
    forge: Forge,
) -> None:
    """Critère 3 : sans la liste, l'écran ne peut que répéter ce qui a été saisi."""
    refused = await forge.client.put(REFERENCE, json={"storage": "inconnu"}, timeout=120)
    read = await forge.client.get(REFERENCE, timeout=120)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == {
        "code": "storage_inconnu",
        "storage": "inconnu",
        "existants": ["comptes", "sites"],
    }
    # Rien n'a été écrit : un refus ne laisse pas un fichier derrière lui.
    assert read.json()["storage"] is None
    assert await forge.file("comptes/reference.yaml") is None


async def test_designating_another_storage_replaces_the_one_reference(forge: Forge) -> None:
    """Une branche a UNE référence de compte : le second réglage remplace, il n'ajoute pas."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    again = await forge.client.put(REFERENCE, json={"storage": "sites"}, timeout=120)

    assert again.json() == {"storage": "sites", "model": "shared/site", "problem": None}
    assert await forge.file("comptes/reference.yaml") == 'storage: "sites"\n'


async def test_writing_the_same_reference_again_produces_no_commit(forge: Forge) -> None:
    """Critère 10 : le rejeu ne fabrique pas un commit qui ne change rien."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    before = await forge.commits()
    again = await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    after = await forge.commits()

    assert again.status_code == 200, again.text
    assert again.headers.get("X-Miles-Unchanged") == "true"
    assert after == before


async def test_the_reference_is_removed_and_removing_again_changes_nothing(
    forge: Forge,
) -> None:
    """Critère 7 : le retrait est un commit, donc relisible et annulable. Et il se rejoue."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    removed = await forge.client.delete(REFERENCE, timeout=120)
    read = await forge.client.get(REFERENCE, timeout=120)
    gone = await forge.file("comptes/reference.yaml")
    before = await forge.commits()
    again = await forge.client.delete(REFERENCE, timeout=120)

    assert removed.status_code == 204
    assert removed.headers.get("X-Miles-Unchanged") is None
    assert read.json()["storage"] is None
    assert gone is None
    assert again.status_code == 204
    assert again.headers.get("X-Miles-Unchanged") == "true"
    assert await forge.commits() == before


async def test_a_file_written_by_hand_that_is_unreadable_is_named(forge: Forge) -> None:
    """Critère 8 : le dépôt fait foi, et une incohérence du dépôt se DIT.

    Compter un fichier fautif comme « aucune référence » laisserait croire qu'il n'y a
    rien à corriger, et le premier terminal réel le découvrirait.
    """
    await forge.seed({"comptes/reference.yaml": "storage: [\n"})
    read = await forge.client.get(REFERENCE, timeout=120)

    assert read.json() == {
        "storage": None,
        "model": None,
        "problem": {"path": "comptes/reference.yaml", "code": "fichier_illisible", "detail": None},
    }


async def test_a_storage_that_disappears_is_signalled_on_the_existing_reference(
    forge: Forge,
) -> None:
    """Critère 9 : signalé SUR le réglage, et le réglage n'est pas réécrit en silence."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    dropped = await forge.client.delete(f"{STORAGES}/comptes", timeout=120)
    read = await forge.client.get(REFERENCE, timeout=120)

    assert dropped.status_code == 204, dropped.text
    assert read.json() == {
        "storage": "comptes",
        "model": None,
        "problem": {
            "path": "comptes/reference.yaml",
            "code": "storage_inconnu",
            "detail": "comptes",
        },
    }
    # Toujours là, intact : Miles ne corrige pas le dépôt de lui-même.
    assert await forge.file("comptes/reference.yaml") == 'storage: "comptes"\n'


async def test_a_storage_broken_outside_miles_is_told_apart_from_a_missing_one(
    forge: Forge,
) -> None:
    """Deux causes, deux codes : « disparu » et « illisible » ne se corrigent pas pareil."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    await forge.seed({"storages/comptes.yaml": "modele: [\n"})
    read = await forge.client.get(REFERENCE, timeout=120)

    assert read.json()["problem"] == {
        "path": "comptes/reference.yaml",
        "code": "storage_illisible",
        "detail": "comptes",
    }


async def test_the_base_branch_is_read_only(forge: Forge) -> None:
    """Critère 5 : même régime que les storages."""
    refused = await forge.client.put(
        REFERENCE, json={"storage": "comptes"}, params={"branch": ROOT}, timeout=120
    )
    read = await forge.client.get(REFERENCE, params={"branch": ROOT}, timeout=120)

    assert refused.status_code == 409, refused.text
    assert read.status_code == 200
    assert read.json()["storage"] is None


async def test_two_branches_carry_two_different_references(forge: Forge) -> None:
    """Critère 4 : c'est la raison d'être du choix « dans git, avec la branche »."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    await forge.publish()
    other = await forge.client.post(
        "/api/workspaces/retrait/branches",
        json={"label": "Essai", "slug": "essai"},
        params={"branch": ROOT},
        timeout=120,
    )
    assert other.status_code == 201, other.text
    held = await forge.client.post("/api/workspaces/retrait/branches/essai/hold", timeout=120)
    assert held.status_code == 201, held.text
    await forge.client.put(REFERENCE, json={"storage": "sites"}, params={"branch": "essai"})

    here = await forge.client.get(REFERENCE, timeout=120)
    there = await forge.client.get(REFERENCE, params={"branch": "essai"}, timeout=120)

    assert here.json()["storage"] == "comptes"
    assert there.json()["storage"] == "sites"


async def test_every_change_is_journalled_with_its_branch(forge: Forge) -> None:
    """Critère 12 : la trace porte la branche et ce qui a changé."""
    await forge.client.put(REFERENCE, json={"storage": "comptes"}, timeout=120)
    await forge.client.delete(REFERENCE, timeout=120)

    rows = await forge.portal.pool.fetch(
        "SELECT type, properties FROM events WHERE type LIKE 'account_reference.%' ORDER BY id"
    )
    written = [(r["type"], json.loads(r["properties"])) for r in rows]

    assert [t for t, _ in written] == ["account_reference.saved", "account_reference.removed"]
    assert written[0][1]["storage"] == "comptes"
    assert all(p["branch"] == "edition" and p["commit"] for _, p in written)


async def test_the_reference_is_read_set_and_removed_through_mcp(m: McpForge) -> None:
    """Critère 11 : les primitives, comme pour les storages et les modèles."""
    empty = await m.ok("get_account_reference", EDIT)
    chosen = await m.ok("set_account_reference", EDIT | {"storage": "comptes"})
    again = await m.ok("set_account_reference", EDIT | {"storage": "comptes"})
    read = await m.ok("get_account_reference", EDIT)
    removed = await m.ok("remove_account_reference", EDIT)
    gone = await m.ok("remove_account_reference", EDIT)

    assert empty["storage"] is None and empty["path"] == "comptes/reference.yaml"
    assert chosen["storage"] == "comptes" and chosen["model"] == "shared/compte"
    assert chosen["unchanged"] is False
    assert again["unchanged"] is True
    assert read["model"] == "shared/compte"
    assert removed == {"removed": True}
    assert gone == {"removed": False}


async def test_mcp_names_the_storages_that_exist_when_the_one_asked_for_does_not(
    m: McpForge,
) -> None:
    refused = await m.refused("set_account_reference", EDIT | {"storage": "inconnu"})

    assert refused["code"] == "storage_inconnu"
    assert refused["existants"] == ["comptes", "sites"]
