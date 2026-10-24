from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from miles.datamodels.schema import normalized, target_of
from tests.integration.git_stack import create_workspace
from tests.integration.test_domains_pg import add_domain
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/data-models"
MODEL_META = "shared/messages/personne.meta.yaml"
# Des JSON Schema 2020-12 en YAML (story 0f7cda10), tels que Miles les enregistre :
# `$schema` et `$id` en tête, posés par le système.
PERSONNE = normalized(
    "title: Personne\ntype: object\nproperties:\n  nom:\n    type: string\n", "shared", "personne"
)
COLIS = normalized(
    """title: Colis
description: Colis tel que le terminal le manipule
type: object
required: [reference]
properties:
  reference:
    type: string
    format: uuid
  destinataire:
    $ref: miles:/shared/personne
  etiquettes:
    type: array
    items:
      type: string
""",
    "suivi",
    "colis",
)


def body_of(content: str) -> dict[str, Any]:
    """Portée, nom et contenu d'une création, lus dans l'`$id` du schéma d'exemple."""
    for line in content.splitlines():
        if line.startswith("$id: "):
            target = target_of(line.removeprefix("$id: ").strip())
            if target is not None:
                return {"scope": target[0], "name": target[1], "content": content}
    raise ValueError("schéma d'exemple sans $id de Miles")


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _create(forge: Forge, schema: str, **override: str) -> httpx.Response:
    return await forge.client.post(ROUTE, json=body_of(schema) | override, timeout=120)


async def test_model_is_written_to_the_work_branch_then_read_back_and_listed(
    forge: Forge,
) -> None:
    await _create(forge, PERSONNE)
    await add_domain(forge)

    created = await _create(forge, COLIS)
    read = await forge.client.get(f"{ROUTE}/suivi/colis", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert created.status_code == 201, created.text
    assert created.json() == {
        "scope": "suivi",
        "name": "colis",
        "path": "domains/suivi/messages/colis.yaml",
        "label": "Colis",
        "version": 1,
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
    other = await _create(forge, PERSONNE.replace("title: Personne", "title: Autre"))

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "nom_pris")
    assert await forge.commits() == before


async def test_refusals_write_nothing_and_say_why(forge: Forge) -> None:
    no_domain = await _create(forge, COLIS)
    await add_domain(forge)
    before = await forge.commits()

    syntax = await _create(forge, PERSONNE, content="type: object\nproperties: [\n")
    meta = await _create(
        forge, PERSONNE, content="type: object\nproperties:\n  a:\n    type: texte\n"
    )
    missing = await _create(forge, COLIS)

    # Un domaine qui n'est pas déclaré ne se crée plus au passage (story 7fa00f56).
    assert (no_domain.status_code, no_domain.json()["detail"]) == (409, "domaine_inconnu")
    assert syntax.status_code == 422
    assert syntax.json()["detail"]["code"] == "yaml_invalide"
    assert syntax.json()["detail"]["line"] is not None
    assert [(p["path"], p["code"]) for p in meta.json()["detail"]["problems"]] == [
        ("properties.a.type", "schema_invalide")
    ]
    # Le transverse « personne » n'existe pas encore : la référence est refusée.
    assert missing.json()["detail"]["problems"] == [
        {
            "path": "properties.destinataire.$ref",
            "code": "modele_inconnu",
            "detail": "shared/personne",
        }
    ]
    assert await forge.commits() == before


async def test_a_shared_model_cannot_reference_a_domain_model(forge: Forge) -> None:
    await add_domain(forge)
    await _create(forge, COLIS.replace("$ref: miles:/shared/personne", "type: string"))
    leaking = PERSONNE + "  colis:\n    $ref: miles:/domains/suivi/colis\n"

    refused = await _create(forge, leaking)

    assert refused.json()["detail"]["problems"] == [
        {"path": "properties.colis.$ref", "code": "modele_inconnu", "detail": "suivi/colis"}
    ]


async def test_referenced_model_cannot_be_deleted_until_its_user_is(forge: Forge) -> None:
    await _create(forge, PERSONNE)
    await add_domain(forge)
    await _create(forge, COLIS)

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
    assert await forge.file(MODEL_META) is None
    assert (again.status_code, again.json()["detail"]) == (404, "modele_inconnu")


async def test_missing_work_branch_is_refused_without_creating_one(forge: Forge) -> None:
    route = f"/api/v1/repos/miles/{forge.name}/branches/back/retrait/edition"
    deleted = await forge.api.delete(route)
    assert deleted.status_code == 204

    refused = await _create(forge, PERSONNE)
    branches = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches")

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "branche_de_travail_introuvable",
    )
    assert "back/retrait/edition" not in [b["name"] for b in branches.json()]


async def test_workspace_without_work_branch_is_refused(forge: Forge) -> None:
    await create_workspace(forge.client, "caisse")

    refused = await forge.client.get("/api/workspaces/caisse/data-models")
    bad_scope = await _create(forge, PERSONNE, scope="../x")

    assert (refused.status_code, refused.json()["detail"]) == (409, "depot_non_configure")
    assert bad_scope.json()["detail"] == {"field": "scope"}


async def test_a_json_sample_becomes_a_schema_without_writing_anything(forge: Forge) -> None:
    """L'import intelligent : on déduit, on n'enregistre pas."""
    before = await forge.client.get(ROUTE, timeout=120)

    inferred = await forge.client.post(
        f"{ROUTE}/inference",
        json={"format": "json", "sample": '{"nom": "Gaël", "vu_le": "2026-10-24"}'},
        timeout=120,
    )
    after = await forge.client.get(ROUTE, timeout=120)

    assert inferred.status_code == 200, inferred.text
    assert inferred.json()["unwrapped"] is False
    assert inferred.json()["schema"] == {
        "type": "object",
        "properties": {
            "nom": {"type": "string"},
            "vu_le": {"type": "string", "format": "date"},
        },
    }
    # Transformation pure : la liste des modèles n'a pas bougé.
    assert after.json() == before.json()


async def test_a_list_sample_yields_the_model_of_one_element(forge: Forge) -> None:
    """Un export est une liste ; un modèle décrit un objet. Le dégagement est annoncé."""
    inferred = await forge.client.post(
        f"{ROUTE}/inference",
        json={"format": "json", "sample": '[{"nom": "a"}, {"nom": "b", "ref": 2}]'},
        timeout=120,
    )

    assert inferred.status_code == 200, inferred.text
    assert inferred.json()["unwrapped"] is True
    assert inferred.json()["schema"]["type"] == "object"
    assert set(inferred.json()["schema"]["properties"]) == {"nom", "ref"}


async def test_a_sample_without_any_object_is_refused_with_its_own_code(forge: Forge) -> None:
    refused = await forge.client.post(
        f"{ROUTE}/inference", json={"format": "json", "sample": "[1, 2]"}, timeout=120
    )

    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "echantillon_sans_objet"


async def test_an_unreadable_sample_is_named_as_such_not_as_an_invalid_schema(
    forge: Forge,
) -> None:
    refused = await forge.client.post(
        f"{ROUTE}/inference", json={"format": "json", "sample": '{"nom": }'}, timeout=120
    )

    assert refused.status_code == 422
    # « echantillon_illisible » et non « yaml_invalide » : l'erreur est dans ce qu'on
    # colle, pas dans le schéma du modèle.
    assert refused.json()["detail"]["code"] == "echantillon_illisible"
    assert refused.json()["detail"]["line"] is not None


async def _declare(
    forge: Forge, label: str = "Personne livrée", slug: str = "personne", scope: str = "shared"
) -> httpx.Response:
    body = {"scope": scope, "label": label, "slug": slug}
    return await forge.client.post(f"{ROUTE}/declarations", json=body, timeout=120)


async def test_a_model_is_declared_by_label_and_slug_then_written_as_a_schema(
    forge: Forge,
) -> None:
    declared = await _declare(forge)
    replay = await _declare(forge)
    other = await _declare(forge, label="Autre label")
    listed = await forge.client.get(ROUTE, timeout=120)
    draft = await forge.client.get(f"{ROUTE}/shared/personne", timeout=120)
    # Le client écrit un autre `$id` : le système le réécrit, le nom ne change pas.
    sent = PERSONNE.replace("$id: miles:/shared/personne", "$id: miles:/shared/autre")
    replaced = await forge.client.put(
        f"{ROUTE}/shared/personne", json={"content": sent}, timeout=120
    )
    same = await forge.client.put(
        f"{ROUTE}/shared/personne", json={"content": PERSONNE}, timeout=120
    )

    assert declared.status_code == 201, declared.text
    assert declared.json() == {
        "scope": "shared",
        "name": "personne",
        "path": "shared/messages/personne.yaml",
        "label": "Personne livrée",
        "version": 1,
    }
    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "nom_pris")
    # Le fichier de métadonnées n'est jamais pris pour un modèle.
    assert [(m["name"], m["label"]) for m in listed.json()] == [("personne", "Personne livrée")]
    assert draft.json()["content"] == normalized(
        "title: Personne livrée\ntype: object\nproperties: {}\n", "shared", "personne"
    )
    # Le label est le `title` : remplacer le schéma l'a changé ; la version est montée.
    assert replaced.status_code == 200, replaced.text
    assert (replaced.json()["label"], replaced.json()["version"]) == ("Personne", 2)
    assert same.headers["x-miles-already-exists"] == "true"
    assert await forge.file(MODEL_META) == "version: 2\n"
    assert await forge.file("shared/messages/personne.yaml") == PERSONNE


async def test_the_version_is_the_systems_and_moves_only_when_the_schema_changes(
    forge: Forge,
) -> None:
    await _create(forge, PERSONNE)
    route = f"{ROUTE}/shared/personne"
    changed = PERSONNE + "  age:\n    type: integer\n"

    same = await forge.client.put(route, json={"content": PERSONNE}, timeout=120)
    first = await forge.client.put(route, json={"content": changed}, timeout=120)
    second = await forge.client.put(
        route, json={"content": changed + "  ville:\n    type: string\n"}, timeout=120
    )
    listed = await forge.client.get(ROUTE, timeout=120)

    assert same.headers["x-miles-already-exists"] == "true"
    assert (first.json()["version"], second.json()["version"]) == (2, 3)
    assert [m["version"] for m in listed.json()] == [3]


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
            "problems": [{"path": "properties", "code": "proprietes_vides", "detail": None}],
        }
    ]
    assert saved.status_code == 201, saved.text


async def test_deleting_a_declared_model_removes_its_metadata_too(forge: Forge) -> None:
    unknown = await _declare(forge, scope="suivi")
    await add_domain(forge)
    await _declare(forge, scope="suivi")

    deleted = await forge.client.delete(f"{ROUTE}/suivi/personne", timeout=120)

    assert (unknown.status_code, unknown.json()["detail"]) == (409, "domaine_inconnu")
    assert deleted.status_code == 204, deleted.text
    assert await forge.file("domains/suivi/messages/personne.meta.yaml") is None
    # Le domaine survit à son dernier modèle : il a été déclaré, il ne se retire pas seul.
    assert await forge.file("domains/suivi/.gitkeep") == ""
    assert await forge.file("domains/suivi/messages/personne.yaml") is None
