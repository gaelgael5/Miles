from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.mcp_stack import McpForge, open_mcp_forge

pytestmark = pytest.mark.integration

EDIT = {"workspace_id": "retrait", "branch": "edition"}
CTX = EDIT | {"context": "accueil"}
# `en-US` est la culture par défaut du workspace de test ; `ar-MA` s'écrit de droite à
# gauche, et c'est elle qui rend mesurable ce qui dépend de la culture.
DEFAULT = "en-US"


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def _context(m: McpForge, name: str = "accueil") -> None:
    created = await m.ok("create_trads_context", EDIT | {"name": name, "label": f"Libellé {name}"})
    assert created["commit"]


async def _culture(m: McpForge, code: str) -> None:
    added = await m.forge.client.post("/api/workspaces/retrait/cultures", json={"culture": code})
    assert added.status_code == 200, added.text


# --- CRUD des contextes ---


async def test_a_context_is_created_read_renamed_and_deleted_through_mcp(m: McpForge) -> None:
    created = await m.ok("create_trads_context", EDIT | {"name": "accueil", "label": "Accueil"})
    listed = await m.ok("list_trads_contexts", EDIT)
    renamed = await m.ok(
        "rename_trads_context", EDIT | {"name": "accueil", "label": "Accueil du terminal"}
    )
    after = await m.ok("list_trads_contexts", EDIT)
    deleted = await m.ok("delete_trads_context", EDIT | {"name": "accueil"})

    assert created["commit"]
    assert listed == [
        {
            "name": "accueil",
            "label": "Accueil",
            "path": "trads/accueil/",
            "keys": 0,
            "translated": {DEFAULT: 0},
            "obsolete": {},
        }
    ]
    assert renamed["label"] == "Accueil du terminal"
    assert after[0]["label"] == "Accueil du terminal"
    assert (deleted["keys"], deleted["values"]) == (0, 0)
    assert await m.ok("list_trads_contexts", EDIT) == []


async def test_a_context_name_already_taken_is_refused_through_mcp(m: McpForge) -> None:
    await _context(m)

    failed, refusal = await m.call(
        "create_trads_context", EDIT | {"name": "accueil", "label": "Autre"}
    )

    assert failed
    assert refusal["code"] == "contexte_pris"


@pytest.mark.parametrize("hostile", ["../evasion", "a/b", "..", "Accueil", "mes écrans"])
async def test_an_invalid_context_name_is_refused_before_touching_the_repository(
    m: McpForge, hostile: str
) -> None:
    failed, _ = await m.call("create_trads_context", EDIT | {"name": hostile, "label": "X"})

    assert failed
    assert await m.ok("list_trads_contexts", EDIT) == []


async def test_an_unknown_context_names_the_ones_that_exist(m: McpForge) -> None:
    """Un agent corrige alors sans tâtonner : c'est le motif de tous les refus de Miles."""
    await _context(m)

    failed, refusal = await m.call("list_trads_keys", EDIT | {"context": "absent"})

    assert failed
    assert refusal["code"] == "contexte_inconnu"
    assert refusal["existants"] == ["accueil"]


# --- CRUD des clés, et l'écriture par culture ---


async def test_a_key_is_created_listed_renamed_and_deleted_through_mcp(m: McpForge) -> None:
    await _context(m)

    created = await m.ok("create_trads_key", CTX | {"slug": "titre", "values": {DEFAULT: "Hello"}})
    listed = await m.ok("list_trads_keys", CTX)
    renamed = await m.ok("rename_trads_key", CTX | {"slug": "titre", "new_slug": "accroche"})
    deleted = await m.ok("delete_trads_key", CTX | {"slug": "accroche"})

    assert created["commit"] and created["written"] == [DEFAULT]
    assert listed == {"keys": [{"slug": "titre", "values": {DEFAULT: "Hello"}}], "total": 1}
    assert renamed["slug"] == "accroche"
    assert deleted["deleted"] == "accroche"
    assert (await m.ok("list_trads_keys", CTX))["keys"] == []


async def test_updating_one_culture_leaves_the_other_files_untouched(m: McpForge) -> None:
    """Seuls les fichiers des cultures présentes sont réécrits : c'est le diff qui y gagne."""
    await _culture(m, "ar-MA")
    await _context(m)
    await m.ok(
        "create_trads_key",
        CTX | {"slug": "titre", "values": {DEFAULT: "Hello", "ar-MA": "مرحبا"}},
    )
    before = await m.forge.file(f"trads/accueil/{DEFAULT}.yaml")

    updated = await m.ok(
        "update_trads_values", CTX | {"slug": "titre", "values": {"ar-MA": "أهلا"}}
    )

    assert updated["written"] == ["ar-MA"]
    assert await m.forge.file(f"trads/accueil/{DEFAULT}.yaml") == before
    keys = (await m.ok("list_trads_keys", CTX))["keys"]
    assert keys[0]["values"] == {DEFAULT: "Hello", "ar-MA": "أهلا"}


async def test_a_null_value_removes_its_line_rather_than_leaving_it_empty(m: McpForge) -> None:
    await _culture(m, "ar-MA")
    await _context(m)
    await m.ok(
        "create_trads_key",
        CTX | {"slug": "titre", "values": {DEFAULT: "Hello", "ar-MA": "مرحبا"}},
    )

    await m.ok("update_trads_values", CTX | {"slug": "titre", "values": {"ar-MA": None}})

    assert "titre" not in (await m.forge.file("trads/accueil/ar-MA.yaml") or "")
    keys = (await m.ok("list_trads_keys", CTX))["keys"]
    # Une culture absente des valeurs n'est pas traduite ; jamais une chaîne vide.
    assert keys[0]["values"] == {DEFAULT: "Hello"}


async def test_emptying_the_default_culture_is_refused_through_mcp(m: McpForge) -> None:
    await _context(m)
    await m.ok("create_trads_key", CTX | {"slug": "titre", "values": {DEFAULT: "Hello"}})

    failed, refusal = await m.call(
        "update_trads_values", CTX | {"slug": "titre", "values": {DEFAULT: None}}
    )

    assert failed
    assert refusal["code"] == "valeur_par_defaut_obligatoire"
    keys = (await m.ok("list_trads_keys", CTX))["keys"]
    assert keys[0]["values"][DEFAULT] == "Hello"


async def test_a_value_that_would_display_otherwise_than_written_is_refused(
    m: McpForge,
) -> None:
    """Et le refus NOMME les caractères : ils sont invisibles, un agent ne les verrait pas."""
    await _context(m)

    failed, refusal = await m.call(
        "create_trads_key", CTX | {"slug": "titre", "values": {DEFAULT: "Hello ‮ world"}}
    )

    assert failed
    assert refusal["code"] == "direction_forcee"
    assert any("U+202E" in found for found in refusal["found"])


async def test_a_culture_outside_the_workspace_is_refused_through_mcp(m: McpForge) -> None:
    await _context(m)
    await m.ok("create_trads_key", CTX | {"slug": "titre", "values": {DEFAULT: "Hello"}})

    failed, refusal = await m.call(
        "update_trads_values", CTX | {"slug": "titre", "values": {"th-TH": "สวัสดี"}}
    )

    assert failed
    assert refusal["code"] == "culture_hors_workspace"


async def test_the_untranslated_filter_gives_an_agent_its_work_list(m: McpForge) -> None:
    await _culture(m, "ar-MA")
    await _context(m)
    await m.ok(
        "create_trads_key",
        CTX | {"slug": "traduite", "values": {DEFAULT: "Hello", "ar-MA": "مرحبا"}},
    )
    await m.ok("create_trads_key", CTX | {"slug": "a-traduire", "values": {DEFAULT: "Bye"}})

    page = await m.ok("list_trads_keys", CTX | {"untranslated": "ar-MA"})

    assert [k["slug"] for k in page["keys"]] == ["a-traduire"]
    assert page["total"] == 1


# --- Les droits : la branche de base ne s'écrit pas, et une clé de lecture non plus ---


async def test_the_base_branch_refuses_every_write_through_mcp(m: McpForge) -> None:
    base = {"workspace_id": "retrait", "branch": "atelier"}

    failed, refusal = await m.call(
        "create_trads_context", base | {"name": "accueil", "label": "Accueil"}
    )

    assert failed
    assert refusal["code"] in ("branche_invalide", "branche_racine_lecture_seule")


async def test_a_context_written_through_mcp_is_the_one_the_screen_reads(m: McpForge) -> None:
    """Les deux chemins écrivent le MÊME dépôt : un agent et un humain se relisent."""
    await _context(m)
    await m.ok("create_trads_key", CTX | {"slug": "titre", "values": {DEFAULT: "Hello"}})

    listed = await m.forge.client.get(
        "/api/workspaces/retrait/trads/accueil/keys", params={"branch": "edition"}, timeout=120
    )

    assert listed.status_code == 200, listed.text
    assert listed.json()["keys"] == [{"slug": "titre", "values": {DEFAULT: "Hello"}}]
