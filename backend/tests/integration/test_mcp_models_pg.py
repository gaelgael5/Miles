from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.obo.signature import sign_actor
from tests.integration.mcp_stack import McpForge, issue_key, open_mcp_forge
from tests.integration.test_datamodels_pg import COLIS, PERSONNE

pytestmark = pytest.mark.integration

WS = {"workspace_id": "retrait"}
EDIT = WS | {"branch": "edition"}


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def _commit(m: McpForge, sha: str) -> dict[str, str]:
    got = await m.forge.api.get(f"/api/v1/repos/miles/{m.forge.name}/git/commits/{sha}")
    commit = got.json()["commit"]
    return {
        "name": commit["author"]["name"],
        "email": commit["author"]["email"],
        "message": commit["message"],
    }


async def test_a_model_is_created_read_replaced_and_deleted_on_a_child_branch(m: McpForge) -> None:
    created = await m.ok("create_data_model", EDIT | {"scope": "shared", "content": PERSONNE})
    replay = await m.ok("create_data_model", EDIT | {"scope": "shared", "content": PERSONNE})
    changed = PERSONNE + "  prenom:\n    type: chaine\n"
    replaced = await m.ok(
        "replace_data_model", EDIT | {"scope": "shared", "name": "personne", "content": changed}
    )
    read = await m.ok("get_data_model", EDIT | {"scope": "shared", "name": "personne"})
    listed = await m.ok("list_data_models", EDIT)
    deleted = await m.ok("delete_data_model", EDIT | {"scope": "shared", "name": "personne"})

    assert created["path"] == "shared/messages/personne.yaml" and created["commit"]
    assert (replay["unchanged"], replay["commit"]) == (True, None)
    assert replaced["commit"] and read["content"] == changed
    assert [e["path"] for e in listed] == ["shared/messages/personne.yaml"]
    assert deleted["commit"] and await m.forge.file("shared/messages/personne.yaml") is None
    assert await m.forge.file("shared/messages/personne.yaml", "work/atelier") is None


async def test_a_change_is_signed_by_the_key_and_journaled_with_it(m: McpForge) -> None:
    created = await m.ok("create_data_model", EDIT | {"scope": "shared", "content": PERSONNE})

    commit = await _commit(m, created["commit"])
    event = await m.forge.portal.pool.fetchrow(
        "SELECT author_directory, author_subject, properties FROM events"
        " WHERE type = 'data_model.created'"
    )

    assert commit["name"] == "Gateway via Miles"
    assert commit["email"] == f"{m.key_id}@apikey.miles.invalid"
    assert "Via la clé d'API « Gateway »." in commit["message"]
    assert event is not None
    assert (event["author_directory"], event["author_subject"]) == ("apikey", m.key_id)
    assert f'"via_api_key": "{m.key_id}"' in event["properties"]


async def test_a_change_made_for_a_signed_person_is_theirs_via_the_key(m: McpForge) -> None:
    guid = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    assert (
        await m.forge.client.put("/api/auth/me/identity", json={"actor": guid})
    ).status_code == 200
    at = int(time.time())
    headers = {
        "x-portal-actor": guid,
        "x-portal-actor-timestamp": str(at),
        "x-portal-actor-signature": sign_actor(guid, at, m.secret),
    }

    created = await m.ok(
        "create_data_model", EDIT | {"scope": "shared", "content": PERSONNE}, headers=headers
    )

    commit = await _commit(m, created["commit"])
    event = await m.forge.portal.pool.fetchrow(
        "SELECT author_directory, author_subject, properties FROM events"
        " WHERE type = 'data_model.created'"
    )
    assert (commit["name"], commit["email"]) == ("admin", "admin@miles.invalid")
    assert "Via la clé d'API « Gateway »." in commit["message"]
    assert event is not None
    assert (event["author_directory"], event["author_subject"]) == ("local", "admin")
    assert f'"via_api_key": "{m.key_id}"' in event["properties"]


async def test_a_change_needs_a_named_child_branch(m: McpForge) -> None:
    before = await m.forge.commits("work/atelier")
    body = {"scope": "shared", "content": PERSONNE}

    missing = await m.refused("create_data_model", WS | body)
    root = await m.refused("create_data_model", WS | body | {"branch": "atelier"})
    unknown = await m.refused("create_data_model", WS | body | {"branch": "nulle"})
    read_root = await m.ok("list_data_models", WS)
    branches = await m.ok("list_branches", WS)

    assert missing == {"code": "branche_requise", "branches": ["edition"]}
    assert root == {"code": "branche_racine_lecture_seule", "branches": ["edition"]}
    assert unknown == {"code": "branche_inconnue", "branche": "nulle", "branches": ["edition"]}
    assert read_root == []
    assert branches == [
        {"slug": "atelier", "label": "atelier", "base": True},
        {"slug": "edition", "label": "Édition", "base": False},
    ]
    assert await m.forge.commits("work/atelier") == before


async def test_rights_refusals_are_named_and_distinct_from_validation(m: McpForge) -> None:
    reader = await issue_key(m.forge, {"retrait": "lecture"}, label="Lecteur")
    body = EDIT | {"scope": "shared", "content": PERSONNE}
    as_reader = {"Authorization": f"Bearer {reader['secret']}"}

    denied = await m.refused("create_data_model", body, headers=as_reader)
    elsewhere = await m.refused("list_data_models", {"workspace_id": "caisse"})

    assert denied == {"code": "droit_insuffisant", "workspace": "retrait", "droit": "lecture"}
    assert elsewhere == {
        "code": "workspace_inconnu",
        "workspace": "caisse",
        "existants": ["retrait"],
    }


async def test_invalid_content_gets_every_problem_the_screen_gets(m: McpForge) -> None:
    broken = "nom: colis\nversion: 1\nproprietes:\n  a:\n    type: inconnu\n  b:\n    type: objet\n"
    by_screen = await m.forge.client.post(
        "/api/workspaces/retrait/data-models", json={"scope": "shared", "content": broken}
    )

    by_mcp = await m.refused("create_data_model", EDIT | {"scope": "shared", "content": broken})
    yaml = await m.refused("create_data_model", EDIT | {"scope": "shared", "content": "a: [b"})
    dangling = await m.refused("create_data_model", EDIT | {"scope": "suivi", "content": COLIS})

    assert by_mcp == {
        "code": "modele_non_conforme",
        "problems": by_screen.json()["detail"]["problems"],
    }
    assert len(by_mcp["problems"]) >= 2
    assert yaml["code"] == "yaml_invalide" and yaml["line"] is not None
    assert dangling["code"] == "modele_non_conforme"
    assert {p["code"] for p in dangling["problems"]} == {"modele_inconnu"}


async def test_unknown_or_used_models_name_what_exists_and_who_uses_them(m: McpForge) -> None:
    await m.ok("create_data_model", EDIT | {"scope": "shared", "content": PERSONNE})
    await m.ok("create_data_model", EDIT | {"scope": "suivi", "content": COLIS})

    unknown = await m.refused("get_data_model", EDIT | {"scope": "shared", "name": "absent"})
    renamed = await m.refused(
        "replace_data_model",
        EDIT
        | {"scope": "shared", "name": "personne", "content": PERSONNE.replace("personne", "autre")},
    )
    used = await m.refused("delete_data_model", EDIT | {"scope": "shared", "name": "personne"})

    assert unknown == {
        "code": "modele_inconnu",
        "path": "shared/messages/absent.yaml",
        "existants": ["domains/suivi/messages/colis.yaml", "shared/messages/personne.yaml"],
    }
    assert renamed == {"code": "nom_fige"}
    assert used == {"code": "modele_utilise", "par": ["domains/suivi/messages/colis.yaml"]}
