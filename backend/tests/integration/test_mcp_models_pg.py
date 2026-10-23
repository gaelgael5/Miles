from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.mcp_stack import McpForge, issue_key, open_mcp_forge
from tests.integration.oauth_helpers import obtain_tokens, open_oauth
from tests.integration.test_datamodels_pg import COLIS, PERSONNE, body_of

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
    created = await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    replay = await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    changed = PERSONNE + "  prenom:\n    type: string\n"
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


async def _forge_identity(m: McpForge) -> tuple[str, str]:
    """Nom et e-mail du compte de forge de l'administrateur, comme Miles les a lus."""
    me = (await m.forge.api.get("/api/v1/user")).json()
    return me.get("full_name") or me["login"], me["email"]


async def test_a_key_alone_cannot_change_anything(m: McpForge) -> None:
    key_only = {"Authorization": f"Bearer {m.secret}"}

    refused = await m.refused("create_data_model", EDIT | body_of(PERSONNE), headers=key_only)
    read = await m.ok("list_data_models", WS, headers=key_only)

    assert refused == {"code": "personne_requise"}
    assert read == []


async def test_a_change_for_the_holder_is_local_until_published_then_theirs(m: McpForge) -> None:
    before = await m.forge.remote_file("shared/messages/personne.yaml")
    created = await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    unpublished = await m.forge.remote_file("shared/messages/personne.yaml")
    published = await m.ok("publish_branch", EDIT)
    again = await m.ok("publish_branch", EDIT)

    commit = await _commit(m, created["commit"])
    event = await m.forge.portal.pool.fetchrow(
        "SELECT author_directory, author_subject, properties FROM events"
        " WHERE type = 'data_model.created'"
    )
    assert (before, unpublished) == (None, None)
    assert (published, again) == (
        {"branch": "edition", "published": 1},
        {"branch": "edition", "published": 0},
    )
    assert (commit["name"], commit["email"]) == await _forge_identity(m)
    assert "Via la clé d'API « Gateway »." in commit["message"]
    assert event is not None
    assert (event["author_directory"], event["author_subject"]) == ("local", "admin")
    assert f'"via_api_key": "{m.key_id}"' in event["properties"]


async def test_a_person_without_the_hold_is_refused_and_told_who_holds_it(m: McpForge) -> None:
    released = await m.forge.client.delete("/api/workspaces/retrait/branches/edition/hold")

    free = await m.refused("create_data_model", EDIT | body_of(PERSONNE))
    publish = await m.refused("publish_branch", EDIT)

    assert released.json() == {"released": True}
    assert free == {"code": "prise_de_main_requise", "par": None}
    assert publish == {"code": "prise_de_main_requise"}


async def test_a_change_needs_a_named_child_branch(m: McpForge) -> None:
    before = await m.forge.commits("work/atelier")
    body = body_of(PERSONNE)

    missing = await m.refused("create_data_model", WS | body)
    root = await m.refused("create_data_model", WS | body | {"branch": "atelier"})
    unknown = await m.refused("create_data_model", WS | body | {"branch": "nulle"})
    read_root = await m.ok("list_data_models", WS)
    branches = await m.ok("list_branches", WS)

    assert missing == {"code": "branche_requise", "branches": ["edition"]}
    assert root == {"code": "branche_racine_lecture_seule", "branches": ["edition"]}
    assert unknown == {"code": "branche_inconnue", "branche": "nulle", "branches": ["edition"]}
    assert read_root == []
    name, _ = await _forge_identity(m)
    login = (await m.forge.api.get("/api/v1/user")).json()["login"]
    assert branches == [
        {"slug": "atelier", "label": "atelier", "base": True, "held_by": None, "held_by_me": False},
        {
            "slug": "edition",
            "label": "Édition",
            "base": False,
            "held_by": f"{name} ({login})",
            "held_by_me": True,
        },
    ]
    assert await m.forge.commits("work/atelier") == before


async def test_rights_refusals_are_named_and_distinct_from_validation(m: McpForge) -> None:
    reader = await issue_key(m.forge, {"retrait": "lecture"}, label="Lecteur")
    body = EDIT | body_of(PERSONNE)
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
    broken = "type: object\nproperties:\n  a:\n    type: inconnu\n  b:\n    minLength: -1\n"
    body = {"scope": "shared", "name": "colis", "content": broken}
    by_screen = await m.forge.client.post("/api/workspaces/retrait/data-models", json=body)

    by_mcp = await m.refused("create_data_model", EDIT | body)
    yaml = await m.refused("create_data_model", EDIT | body | {"content": "a: [b"})
    # Le domaine se déclare d'abord (story 7fa00f56) ; ensuite seulement, la référence.
    no_domain = await m.refused("create_data_model", EDIT | body_of(COLIS))
    await m.ok("create_domain", EDIT | {"name": "suivi"})
    dangling = await m.refused("create_data_model", EDIT | body_of(COLIS))

    assert by_mcp == {
        "code": "modele_non_conforme",
        "problems": by_screen.json()["detail"]["problems"],
    }
    assert len(by_mcp["problems"]) >= 2
    assert yaml["code"] == "yaml_invalide" and yaml["line"] is not None
    assert no_domain == {"code": "domaine_inconnu"}
    assert dangling["code"] == "modele_non_conforme"
    assert {p["code"] for p in dangling["problems"]} == {"modele_inconnu"}


async def test_unknown_or_used_models_name_what_exists_and_who_uses_them(m: McpForge) -> None:
    await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    await m.ok("create_domain", EDIT | {"name": "suivi"})
    await m.ok("create_data_model", EDIT | body_of(COLIS))

    unknown = await m.refused("get_data_model", EDIT | {"scope": "shared", "name": "absent"})
    external = await m.refused(
        "replace_data_model",
        EDIT
        | {
            "scope": "shared",
            "name": "personne",
            "content": PERSONNE + "  x:\n    $ref: https://ailleurs/x.json\n",
        },
    )
    used = await m.refused("delete_data_model", EDIT | {"scope": "shared", "name": "personne"})

    assert unknown == {
        "code": "modele_inconnu",
        "path": "shared/messages/absent.yaml",
        "existants": ["domains/suivi/messages/colis.yaml", "shared/messages/personne.yaml"],
    }
    assert external["code"] == "modele_non_conforme"
    assert {p["code"] for p in external["problems"]} == {"reference_externe"}
    assert used == {"code": "modele_utilise", "par": ["domains/suivi/messages/colis.yaml"]}


async def test_a_change_made_through_oauth_is_signed_by_the_person_via_the_client(
    m: McpForge,
) -> None:
    open_oauth(m.forge.portal)
    _, tokens = await obtain_tokens(m.forge.client, m.mcp, {"retrait": "ecriture"})
    as_person = {"Authorization": f"Bearer {tokens['access_token']}"}

    created = await m.ok("create_data_model", EDIT | body_of(PERSONNE), headers=as_person)

    await m.forge.publish()
    commit = await _commit(m, created["commit"])
    event = await m.forge.portal.pool.fetchrow(
        "SELECT author_directory, author_subject, properties FROM events"
        " WHERE type = 'data_model.created'"
    )
    assert (commit["name"], commit["email"]) == await _forge_identity(m)
    assert "Via le client OAuth « claude.ai »." in commit["message"]
    assert event is not None
    assert (event["author_directory"], event["author_subject"]) == ("local", "admin")
    assert '"via_oauth_grant"' in event["properties"]


async def test_a_domain_is_created_once_and_its_name_is_checked(m: McpForge) -> None:
    created = await m.ok("create_domain", EDIT | {"name": "suivi"})
    replay = await m.ok("create_domain", EDIT | {"name": "suivi"})
    bad = await m.refused("create_domain", EDIT | {"name": "../x"})
    listed = await m.ok("list_domains", EDIT)

    assert created["commit"] and created["unchanged"] is False
    assert (replay["unchanged"], replay["commit"]) == (True, None)
    assert (bad["code"], bad["champ"]) == ("champ_invalide", "name")
    assert listed["domains"] == ["suivi"]
    assert await m.forge.file("domains/suivi/.gitkeep") == ""
    # Écrit dans la branche enfant seulement : la racine reste en lecture seule.
    assert await m.forge.file("domains/suivi/.gitkeep", "work/atelier") is None
