from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.git_stack import create_workspace
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/data-models"
MODEL_META = "shared/messages/personne.meta.yaml"
PERSONNE = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n"
COLIS = """nom: colis
version: 2
description: Colis tel que le terminal le manipule
proprietes:
  reference:
    type: chaine
    obligatoire: true
  destinataire:
    type: objet
    modele: personne
  etiquettes:
    type: liste
    elements:
      type: chaine
"""


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _create(forge: Forge, content: str, scope: str = "shared") -> httpx.Response:
    return await forge.client.post(ROUTE, json={"scope": scope, "content": content}, timeout=120)


async def test_model_is_written_to_the_work_branch_then_read_back_and_listed(
    forge: Forge,
) -> None:
    await _create(forge, PERSONNE)

    created = await _create(forge, COLIS, scope="suivi")
    read = await forge.client.get(f"{ROUTE}/suivi/colis", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert created.status_code == 201, created.text
    assert created.json() == {
        "scope": "suivi",
        "name": "colis",
        "path": "domains/suivi/messages/colis.yaml",
        # Créé par son YAML : pas de label (4a329076).
        "label": None,
    }
    assert await forge.file("domains/suivi/messages/colis.yaml") == COLIS
    assert read.json()["content"] == COLIS
    assert [(m["scope"], m["name"]) for m in listed.json()] == [
        ("suivi", "colis"),
        ("shared", "personne"),
    ]
    events = await forge.portal.pool.fetch(
        "SELECT properties->>'path' AS path FROM events WHERE type = 'data_model.created'"
        " ORDER BY written_at"
    )
    assert [e["path"] for e in events] == [
        "shared/messages/personne.yaml",
        "domains/suivi/messages/colis.yaml",
    ]


async def test_replay_writes_nothing_and_a_different_content_is_a_conflict(forge: Forge) -> None:
    await _create(forge, PERSONNE)
    before = await forge.commits()

    replay = await _create(forge, PERSONNE)
    other = await _create(forge, PERSONNE.replace("version: 1", "version: 2"))

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "nom_pris")
    assert await forge.commits() == before


async def test_refusals_write_nothing_and_say_why(forge: Forge) -> None:
    before = await forge.commits()

    syntax = await _create(forge, "nom: x\nproprietes: [\n")
    grammar = await _create(forge, "nom: x\nversion: 1\nproprietes:\n  a:\n    type: texte\n")
    missing = await _create(forge, COLIS)

    assert syntax.status_code == 422
    assert syntax.json()["detail"]["code"] == "yaml_invalide"
    assert syntax.json()["detail"]["line"] is not None
    assert grammar.json()["detail"]["problems"] == [
        {"path": "proprietes.a.type", "code": "type_inconnu", "detail": "texte"}
    ]
    # Un transverse ne voit pas les modèles de domaine, et personne n'existe pas encore.
    assert missing.json()["detail"]["problems"] == [
        {"path": "proprietes.destinataire.modele", "code": "modele_inconnu", "detail": "personne"}
    ]
    assert await forge.commits() == before


async def test_referenced_model_cannot_be_deleted_until_its_user_is(forge: Forge) -> None:
    await _create(forge, PERSONNE)
    await _create(forge, COLIS, scope="suivi")

    refused = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)
    user_deleted = await forge.client.delete(f"{ROUTE}/suivi/colis", timeout=120)
    deleted = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)
    again = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)

    assert refused.json()["detail"] == {
        "code": "utilise",
        "by": ["domains/suivi/messages/colis.yaml"],
    }
    assert (user_deleted.status_code, deleted.status_code) == (204, 204)
    assert await forge.file("shared/messages/personne.yaml") is None
    assert (again.status_code, again.json()["detail"]) == (404, "modele_inconnu")


async def test_missing_work_branch_is_refused_without_creating_one(forge: Forge) -> None:
    deleted = await forge.api.delete(f"/api/v1/repos/miles/{forge.name}/branches/work/edition")
    assert deleted.status_code == 204

    refused = await _create(forge, PERSONNE)
    branches = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches")

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "branche_de_travail_introuvable",
    )
    assert "work/edition" not in [b["name"] for b in branches.json()]


async def test_workspace_without_work_branch_is_refused(forge: Forge) -> None:
    await create_workspace(forge.client, "caisse")

    refused = await forge.client.get("/api/workspaces/caisse/data-models")
    bad_scope = await forge.client.post(ROUTE, json={"scope": "../x", "content": PERSONNE})

    assert (refused.status_code, refused.json()["detail"]) == (409, "depot_non_configure")
    assert bad_scope.json()["detail"] == {"field": "scope"}


async def _declare(
    forge: Forge, label: str = "Personne livrée", slug: str = "personne", scope: str = "shared"
) -> httpx.Response:
    body = {"scope": scope, "label": label, "slug": slug}
    return await forge.client.post(f"{ROUTE}/declarations", json=body, timeout=120)


async def test_a_model_is_declared_by_label_and_slug_then_written_in_yaml(forge: Forge) -> None:
    declared = await _declare(forge)
    replay = await _declare(forge)
    other = await _declare(forge, label="Autre label")
    listed = await forge.client.get(ROUTE, timeout=120)
    draft = await forge.client.get(f"{ROUTE}/shared/personne", timeout=120)
    replaced = await forge.client.put(
        f"{ROUTE}/shared/personne", json={"content": PERSONNE}, timeout=120
    )
    same = await forge.client.put(
        f"{ROUTE}/shared/personne", json={"content": PERSONNE}, timeout=120
    )
    renamed = await forge.client.put(
        f"{ROUTE}/shared/personne",
        json={"content": PERSONNE.replace("nom: personne", "nom: autre")},
        timeout=120,
    )

    assert declared.status_code == 201, declared.text
    assert declared.json() == {
        "scope": "shared",
        "name": "personne",
        "path": "shared/messages/personne.yaml",
        "label": "Personne livrée",
    }
    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "nom_pris")
    # Le fichier de métadonnées n'est jamais pris pour un modèle.
    assert [(m["name"], m["label"]) for m in listed.json()] == [("personne", "Personne livrée")]
    assert draft.json()["content"] == "nom: personne\nversion: 1\nproprietes: {}\n"
    assert replaced.status_code == 200 and replaced.json()["label"] == "Personne livrée"
    assert same.headers["x-miles-already-exists"] == "true"
    assert (renamed.status_code, renamed.json()["detail"]) == (409, "nom_fige")
    assert await forge.file(MODEL_META) == "libelle: Personne livrée\n"
    assert await forge.file("shared/messages/personne.yaml") == PERSONNE


async def test_an_empty_model_is_kept_as_a_draft_but_blocks_a_version(forge: Forge) -> None:
    await _declare(forge)
    await forge.publish()

    blocked = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Brouillon"}, timeout=120
    )
    await forge.client.put(f"{ROUTE}/shared/personne", json={"content": PERSONNE}, timeout=120)
    await forge.publish()
    saved = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Complet"}, timeout=120
    )

    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"]["reports"] == [
        {
            "path": "shared/messages/personne.yaml",
            "problems": [{"path": "proprietes", "code": "proprietes_vides", "detail": None}],
        }
    ]
    assert saved.status_code == 201, saved.text


async def test_deleting_a_declared_model_removes_its_label_too(forge: Forge) -> None:
    await _declare(forge, scope="suivi")

    deleted = await forge.client.delete(f"{ROUTE}/suivi/personne", timeout=120)

    assert deleted.status_code == 204, deleted.text
    assert await forge.file("domains/suivi/messages/personne.meta.yaml") is None
    assert await forge.file("domains/suivi/messages/personne.yaml") is None
