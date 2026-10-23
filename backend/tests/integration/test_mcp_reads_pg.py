from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.mcp_stack import McpForge, open_mcp_forge
from tests.integration.test_contracts_pg import SUIVI, _declare, _import
from tests.integration.test_datamodels_pg import COLIS, PERSONNE, body_of
from tests.integration.work_stack import EDITED

pytestmark = pytest.mark.integration

WS = {"workspace_id": "retrait"}
EDIT = WS | {"branch": "edition"}


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def _head(m: McpForge) -> str:
    got = await m.forge.api.get(f"/api/v1/repos/miles/{m.forge.name}/branches/{EDITED}")
    return str(got.json()["commit"]["id"])


async def _outside(m: McpForge, path: str, content: str) -> None:
    written = await m.forge.api.post(
        f"/api/v1/repos/miles/{m.forge.name}/contents/{path}",
        json={"branch": EDITED, "content": base64.b64encode(content.encode()).decode()},
    )
    assert written.status_code == 201, written.text


async def _populate(m: McpForge) -> str:
    """Un pivot transverse, un domaine « suivi », un contrat ; rend la tête d'avant."""
    await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    await m.forge.publish()
    before = await _head(m)
    await m.ok("create_data_model", EDIT | body_of(COLIS))
    assert (await _declare(m.forge)).status_code == 201
    assert (await _import(m.forge, SUIVI)).status_code == 201
    await m.forge.publish()
    await _outside(m, "domains/suivi/mappings/inbound/depot.jslt", "{ }\n")
    await _outside(m, "domains/suivi/notes.txt", "égaré\n")
    return before


async def test_a_whole_domain_comes_in_one_call_with_stray_files_named(m: McpForge) -> None:
    await _populate(m)

    listed = await m.ok("list_domains", EDIT)
    domain = await m.ok("get_domain", EDIT | {"domain": "suivi"})
    shared = await m.ok("get_shared_messages", EDIT)

    assert listed["domains"] == ["suivi"]
    sections = domain["sections"]
    assert [e["path"] for e in sections["messages"]] == ["domains/suivi/messages/colis.yaml"]
    assert sections["messages"][0]["content"] == COLIS
    assert [e["path"] for e in sections["mappings/inbound"]] == [
        "domains/suivi/mappings/inbound/depot.jslt"
    ]
    assert sections["screens"] == [] and sections["scenarios"] == []
    assert domain["misplaced"] == [{"path": "domains/suivi/notes.txt", "content": "égaré\n"}]
    assert (domain["truncated"], domain["next_after"]) == (False, None)
    assert shared["messages"] == [{"path": "shared/messages/personne.yaml", "content": PERSONNE}]


async def test_an_unknown_domain_names_those_that_exist(m: McpForge) -> None:
    await _populate(m)

    unknown = await m.refused("get_domain", EDIT | {"domain": "absent"})
    invalid = await m.refused("get_domain", EDIT | {"domain": "../shared"})

    assert unknown == {"code": "domaine_inconnu", "domaine": "absent", "existants": ["suivi"]}
    assert invalid["code"] == "champ_invalide"


async def test_a_contract_its_versions_and_the_operations_of_one(m: McpForge) -> None:
    await _populate(m)

    listed = await m.ok("list_contracts", EDIT)
    one = await m.ok("get_contract", EDIT | {"contract": "suivi", "version": 1})
    unknown_version = await m.refused("get_contract", EDIT | {"contract": "suivi", "version": 9})
    unknown = await m.refused("get_contract", EDIT | {"contract": "absent"})

    assert [(c["slug"], [v["number"] for v in c["versions"]]) for c in listed["contracts"]] == [
        ("suivi", [1])
    ]
    assert one["versions"][0]["title"] == "Suivi des demandes"
    assert one["operations"] == [
        {"method": "get", "path": "/demandes", "operation_id": "listerDemandes"}
    ]
    assert unknown_version == {"code": "version_inconnue", "version": 9, "existantes": [1]}
    assert unknown == {"code": "contrat_inconnu", "contrat": "absent", "existants": ["suivi"]}


async def test_reading_at_a_commit_gives_that_state_not_the_current_one(m: McpForge) -> None:
    before = await _populate(m)

    then = await m.ok("list_domains", EDIT | {"commit": before})
    then_catalog = await m.ok("get_catalog", EDIT | {"commit": before})
    now_catalog = await m.ok("get_catalog", EDIT)
    unknown = await m.refused("list_domains", EDIT | {"commit": "0" * 40})

    assert (then["commit"], then["domains"]) == (before, [])
    assert [x["name"] for x in then_catalog["models"]] == ["personne"]
    assert sorted(x["name"] for x in now_catalog["models"]) == ["colis", "personne"]
    assert {"concat"} <= {f["name"] for f in now_catalog["functions"]}
    assert unknown == {"code": "commit_inconnu", "commit": "0" * 40}


async def test_reads_need_a_right_on_the_workspace(m: McpForge) -> None:
    refused = await m.refused("list_domains", {"workspace_id": "caisse"})

    assert refused["code"] == "workspace_inconnu"
