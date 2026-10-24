from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.mcp_stack import McpForge, open_mcp_forge
from tests.integration.test_datamodels_pg import body_of
from tests.integration.test_sources_pg import COMPTE, SOURCE, STORAGE

pytestmark = pytest.mark.integration

EDIT = {"workspace_id": "retrait", "branch": "edition"}
STEPS = [
    {"name": "normaliser", "template": '{ "code": $.code }', "target": None},
    {"name": "statut", "template": '"ok"', "target": "$.statut"},
]
# Rendues par l'outil : une étape porte toujours ses deux modèles (24/10/2026).
READ_STEPS = [s | {"source_model": None, "destination_model": None} for s in STEPS]


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def test_a_chain_is_saved_read_listed_and_deleted_through_mcp(m: McpForge) -> None:
    saved = await m.ok("save_chain", EDIT | {"slug": "import", "label": "Import", "steps": STEPS})
    replay = await m.ok("save_chain", EDIT | {"slug": "import", "label": "Import", "steps": STEPS})
    read = await m.ok("get_chain", EDIT | {"slug": "import"})
    listed = await m.ok("list_chains", EDIT)
    deleted = await m.ok("delete_chain", EDIT | {"slug": "import"})

    assert saved["path"] == "transformations/import/" and saved["commit"]
    assert (replay["unchanged"], replay["commit"]) == (True, None)
    assert read["steps"] == READ_STEPS
    assert listed == [{"slug": "import", "label": "Import", "steps": 2}]
    assert deleted["commit"] and await m.forge.file("transformations/import/chain.json") is None


async def test_an_invalid_chain_gets_every_step_problem_the_screen_gets(m: McpForge) -> None:
    steps = [
        {"name": "a", "template": "{ ", "target": None},
        {"name": "b", "template": "$.x + 1", "target": "$.lignes[*]"},
    ]
    by_screen = await m.forge.client.put(
        "/api/workspaces/retrait/transformations/import", json={"label": "Import", "steps": steps}
    )

    by_mcp = await m.refused(
        "save_chain", EDIT | {"slug": "import", "label": "Import", "steps": steps}
    )

    assert by_mcp == {"code": "chaine_invalide", "problems": by_screen.json()["detail"]["problems"]}
    assert {p["step"] for p in by_mcp["problems"]} == {0, 1}


async def test_trying_a_chain_writes_nothing_and_matches_the_screen(m: McpForge) -> None:
    before = await m.forge.commits()
    sample = {"code": "C-42", "autre": 1}
    by_screen = await m.forge.client.post(
        "/api/transformations/check",
        # L'essai de l'écran ne prend que template et cible : le nom ne sert qu'au stockage.
        json={
            "steps": [{k: s[k] for k in ("template", "target")} for s in STEPS],
            "sample": sample,
        },
    )

    tried = await m.ok("try_chain", {"steps": STEPS, "sample": sample})

    assert tried == by_screen.json()
    assert tried["trace"][-1] == {"code": "C-42", "statut": "ok"}
    assert await m.forge.commits() == before


async def test_unknown_or_designated_chains_name_what_exists_and_who_uses_them(
    m: McpForge,
) -> None:
    await m.ok("create_data_model", EDIT | body_of(COMPTE))
    await m.ok("save_chain", EDIT | {"slug": "comptes-import", "label": "Import", "steps": STEPS})
    # La source désigne un storage depuis le 24/10/2026 : il existe avant elle.
    stored = await m.forge.client.post(
        "/api/workspaces/retrait/storages", json=STORAGE, timeout=120
    )
    assert stored.status_code == 201, stored.text
    declared = await m.forge.client.post(
        "/api/workspaces/retrait/sources", json=SOURCE, timeout=120
    )
    assert declared.status_code == 201, declared.text

    unknown = await m.refused("get_chain", EDIT | {"slug": "absente"})
    used = await m.refused("delete_chain", EDIT | {"slug": "comptes-import"})

    assert unknown == {
        "code": "chaine_inconnue",
        "slug": "absente",
        "existants": ["comptes-import"],
    }
    assert used == {"code": "chaine_utilisee", "par": ["comptes"]}


async def test_saving_through_mcp_keeps_the_models_the_screen_had_set(m: McpForge) -> None:
    """Ils se relisent de l'entrée : les laisser tomber les effaçait sans un mot."""
    steps = [STEPS[0] | {"source_model": "miles:/shared/brut", "destination_model": None}]
    await m.ok("save_chain", EDIT | {"slug": "import", "label": "Import", "steps": steps})

    read = await m.ok("get_chain", EDIT | {"slug": "import"})

    assert read["steps"][0]["source_model"] == "miles:/shared/brut"
