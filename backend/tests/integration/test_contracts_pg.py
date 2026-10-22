from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/contracts"
SUIVI = """openapi: 3.0.3
info:
  title: Suivi des demandes
  version: "1.2"
paths:
  /demandes:
    get:
      operationId: listerDemandes
      responses:
        "200": {description: ok}
"""
SUIVI_V2 = SUIVI.replace('"1.2"', '"2.0"')
EMPTY = 'openapi: 3.1.0\ninfo: {title: Vide, version: "1"}\npaths: {}\n'
LABEL = "Suivi : demandes # tiers"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _declare(
    forge: Forge, slug: str = "suivi", label: str = LABEL, sens: str | None = "sortant"
) -> httpx.Response:
    body = {"slug": slug, "label": label} | ({"sens": sens} if sens else {})
    return await forge.client.post(ROUTE, json=body, timeout=120)


async def _import(forge: Forge, content: str, slug: str = "suivi") -> httpx.Response:
    body = {"content": content}
    return await forge.client.post(f"{ROUTE}/{slug}/versions", json=body, timeout=120)


async def test_contract_is_declared_then_its_files_coexist_as_versions(forge: Forge) -> None:
    declared = await _declare(forge)
    first = await _import(forge, SUIVI)
    second = await _import(forge, SUIVI_V2)
    detail = await forge.client.get(f"{ROUTE}/suivi", timeout=120)

    assert declared.status_code == 201, declared.text
    assert declared.json() == {"slug": "suivi", "label": LABEL, "sens": "sortant", "versions": []}
    assert (first.status_code, first.json()["number"]) == (201, 1)
    assert (second.status_code, second.json()["number"]) == (201, 2)
    assert await forge.file("contracts/suivi/v1.yaml") == SUIVI
    assert await forge.file("contracts/suivi/v2.yaml") == SUIVI_V2
    assert await forge.file("contracts/suivi/contract.yaml") == (
        'slug: suivi\nlabel: "Suivi : demandes # tiers"\nsens: sortant\n'
    )
    assert [v["number"] for v in detail.json()["versions"]] == [1, 2]
    assert detail.json()["versions"][0]["operation_list"] == [
        {"method": "get", "path": "/demandes", "operation_id": "listerDemandes"}
    ]


async def test_declared_contracts_are_listed_with_their_versions(forge: Forge) -> None:
    await _declare(forge)
    await _declare(forge, "vide", "Sans opération", "entrant")
    await _import(forge, EMPTY, "vide")

    listed = await forge.client.get(ROUTE, timeout=120)

    assert listed.json() == [
        {"slug": "suivi", "label": LABEL, "sens": "sortant", "versions": []},
        {
            "slug": "vide",
            "label": "Sans opération",
            "sens": "entrant",
            "versions": [
                {"number": 1, "title": "Vide", "operations": 0, "warnings": ["aucune_operation"]}
            ],
        },
    ]


async def test_replays_write_nothing_and_a_taken_slug_names_its_occupant(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, SUIVI)
    before = await forge.commits()

    redeclared = await _declare(forge)
    reimported = await _import(forge, SUIVI)
    taken = await _declare(forge, label="Autre chose")
    turned = await _declare(forge, sens="entrant")

    assert (redeclared.status_code, redeclared.headers["x-miles-already-exists"]) == (200, "true")
    assert (reimported.status_code, reimported.json()["number"]) == (200, 1)
    assert taken.json()["detail"] == {"code": "slug_pris", "by": LABEL}
    assert turned.status_code == 409
    assert await forge.commits() == before


async def test_declaration_is_frozen(forge: Forge) -> None:
    await _declare(forge)

    renamed = await forge.client.patch(f"{ROUTE}/suivi", json={"slug": "autre"})
    relabelled = await forge.client.patch(f"{ROUTE}/suivi", json={"label": "Autre"})
    turned = await forge.client.patch(f"{ROUTE}/suivi", json={"sens": "entrant"})

    assert (renamed.status_code, renamed.json()["detail"]) == (409, "slug_fige")
    assert relabelled.json()["detail"] == "label_fige"
    assert turned.json()["detail"] == "sens_fige"


async def test_refusals_write_nothing_and_say_why(forge: Forge) -> None:
    before = await forge.commits()

    no_direction = await _declare(forge, sens=None)
    empty_slug = await _declare(forge, slug="   ")
    bad_slug = await _declare(forge, slug="Suivi!")
    no_label = await _declare(forge, label="  ")
    undeclared = await _import(forge, SUIVI, "inconnu")
    await _declare(forge)
    declared = await forge.commits()
    unreadable = await _import(forge, "openapi: [\n")
    swagger = await _import(forge, "swagger: '2.0'\ninfo: {title: x}\n")
    invalid = await _import(forge, EMPTY.replace(', version: "1"', ""))

    assert no_direction.json()["detail"] == {"field": "sens"}
    assert empty_slug.json()["detail"] == {"field": "slug", "reason": "vide"}
    assert bad_slug.json()["detail"] == {"field": "slug"}
    assert no_label.json()["detail"] == {"field": "label", "reason": "vide"}
    assert (undeclared.status_code, undeclared.json()["detail"]) == (404, "contrat_inconnu")
    assert declared == before + 1
    assert unreadable.json()["detail"]["code"] == "openapi_illisible"
    assert unreadable.json()["detail"]["line"] is not None
    assert swagger.json()["detail"] == {
        "code": "version_non_prise_en_charge",
        "found": "2.0",
        "accepted": ["3.0", "3.1"],
    }
    assert invalid.json()["detail"]["code"] == "openapi_invalide"
    assert await forge.commits() == declared


async def test_a_version_cannot_freeze_a_declared_contract_without_file(forge: Forge) -> None:
    await _declare(forge)

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Contrat vide"}, timeout=120
    )
    await _import(forge, SUIVI)
    saved = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Contrat complet"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": "contracts/suivi/contract.yaml",
            "problems": [{"path": "", "code": "contrat_sans_fichier", "detail": None}],
        }
    ]
    assert saved.status_code == 201, saved.text


async def test_a_version_cannot_freeze_a_contract_broken_outside_miles(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, SUIVI)
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        params={"ref": "work/atelier"},
    )
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        json={
            "branch": "work/atelier",
            "sha": meta.json()["sha"],
            # « slug: suivi », « sens: lateral » : un sens hors liste, en base64.
            "content": "c2x1Zzogc3VpdmkKc2VuczogbGF0ZXJhbAo=",
        },
    )
    assert changed.status_code == 200, changed.text

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Contrat cassé"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": "contracts/suivi/contract.yaml",
            "problems": [{"path": "", "code": "metadonnees_de_contrat_invalides", "detail": None}],
        }
    ]


async def test_reading_an_address_refuses_the_server_itself_and_names_why(forge: Forge) -> None:
    looped = await forge.client.post(f"{ROUTE}/fetch", json={"url": "http://127.0.0.1:8080/x"})
    malformed = await forge.client.post(f"{ROUTE}/fetch", json={"url": "file:///etc/passwd"})

    assert (looped.status_code, looped.json()["detail"]) == (
        422,
        {"code": "lecture_distante", "reason": "adresse_interdite"},
    )
    assert malformed.json()["detail"] == {"code": "lecture_distante", "reason": "adresse_invalide"}
