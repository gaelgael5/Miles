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
    forge: Forge, slug: str = "suivi", label: str = LABEL, sens: str | None = "externe"
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
    assert declared.json() == {"slug": "suivi", "label": LABEL, "sens": "externe", "versions": []}
    assert (first.status_code, first.json()["number"]) == (201, 1)
    assert (second.status_code, second.json()["number"]) == (201, 2)
    assert await forge.file("contracts/suivi/v1.yaml") == SUIVI
    assert await forge.file("contracts/suivi/v2.yaml") == SUIVI_V2
    meta = await forge.file("contracts/suivi/contract.yaml")
    assert meta is not None
    assert meta.startswith('slug: suivi\nlabel: "Suivi : demandes # tiers"\nsens: externe\n')
    versions = detail.json()["versions"]
    assert [v["number"] for v in versions] == [1, 2]
    assert versions[0]["operation_list"] == [
        {"method": "get", "path": "/demandes", "operation_id": "listerDemandes", "change": None}
    ]
    # Date et auteur du dépôt, tenus dans git avec le contrat.
    assert all(v["imported_at"] is not None for v in versions)
    assert versions[1]["imported_by"].startswith("admin via Miles <")


async def test_a_version_serves_its_openapi_for_the_swagger_viewer(forge: Forge) -> None:
    """Gael, 25/10/2026 : chaque version porte un bouton vers le visualiseur Swagger."""
    await _declare(forge)
    await _import(forge, SUIVI)

    spec = await forge.client.get(f"{ROUTE}/suivi/versions/1/openapi", timeout=120)

    assert spec.status_code == 200, spec.text
    body = spec.json()
    # Le document INTÉGRÉ, rendu en objet : le dépôt garde du YAML, pas le navigateur.
    assert body["openapi"].startswith("3.")
    assert "/demandes" in body["paths"]


async def test_an_absent_version_has_no_openapi(forge: Forge) -> None:
    await _declare(forge)

    absent = await forge.client.get(f"{ROUTE}/suivi/versions/9/openapi", timeout=120)

    assert (absent.status_code, absent.json()["detail"]) == (404, "contrat_inconnu")


async def test_a_new_version_shows_what_it_adds_and_what_it_no_longer_exposes(
    forge: Forge,
) -> None:
    v2 = SUIVI.replace(
        "  /demandes:\n    get:\n      operationId: listerDemandes\n",
        "  /colis:\n    post:\n      operationId: deposerColis\n",
    )
    await _declare(forge)
    await _import(forge, SUIVI)

    imported = await _import(forge, v2)
    detail = await forge.client.get(f"{ROUTE}/suivi", timeout=120)
    redeclared = await _declare(forge)

    assert imported.json()["compared_with"] == 1
    assert imported.json()["operation_list"] == [
        {"method": "post", "path": "/colis", "operation_id": "deposerColis", "change": "nouvelle"}
    ]
    assert imported.json()["removed"] == [
        {"method": "get", "path": "/demandes", "operation_id": "listerDemandes"}
    ]
    first = detail.json()["versions"][0]
    assert (first["compared_with"], first["removed"]) == (None, [])
    # L'ancienne version reste entière : ses opérations servent tant que le tiers l'expose.
    assert await forge.file("contracts/suivi/v1.yaml") == SUIVI
    # Les dépôts ne changent pas l'identité déclarée : le rejeu reste un rejeu.
    assert (redeclared.status_code, redeclared.headers["x-miles-already-exists"]) == (200, "true")


async def test_declared_contracts_are_listed_with_their_versions(forge: Forge) -> None:
    await _declare(forge)
    await _declare(forge, "vide", "Sans opération", "interne")
    await _import(forge, EMPTY, "vide")

    listed = await forge.client.get(ROUTE, timeout=120)

    assert listed.json()[1]["versions"][0]["imported_at"] is not None
    assert listed.json() == [
        {"slug": "suivi", "label": LABEL, "sens": "externe", "versions": []},
        {
            "slug": "vide",
            "label": "Sans opération",
            "sens": "interne",
            "versions": [
                {
                    "number": 1,
                    "title": "Vide",
                    "operations": 0,
                    "warnings": ["aucune_operation"],
                    "imported_at": listed.json()[1]["versions"][0]["imported_at"],
                    "imported_by": listed.json()[1]["versions"][0]["imported_by"],
                    # Sans `components/schemas` : aucun modèle, et c'est à jour (47f55d8b).
                    "models": [],
                    "models_state": "a_jour",
                }
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
    turned = await _declare(forge, sens="interne")

    assert (redeclared.status_code, redeclared.headers["x-miles-already-exists"]) == (200, "true")
    assert (reimported.status_code, reimported.json()["number"]) == (200, 1)
    assert taken.json()["detail"] == {"code": "slug_pris", "by": LABEL}
    assert turned.status_code == 409
    assert await forge.commits() == before


async def test_declaration_is_frozen(forge: Forge) -> None:
    await _declare(forge)

    renamed = await forge.client.patch(f"{ROUTE}/suivi", json={"slug": "autre"})
    relabelled = await forge.client.patch(f"{ROUTE}/suivi", json={"label": "Autre"})
    turned = await forge.client.patch(f"{ROUTE}/suivi", json={"sens": "interne"})

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
    # Une version fige la tête publiée (9def0adc) : on publie avant chaque enregistrement.
    await forge.publish()

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Contrat vide"}, timeout=120
    )
    await _import(forge, SUIVI)
    await forge.publish()
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
    await forge.publish()
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        params={"ref": "back/retrait/edition"},
    )
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/contracts/suivi/contract.yaml",
        json={
            "branch": "back/retrait/edition",
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


async def test_a_contract_is_deleted_with_all_its_versions(forge: Forge) -> None:
    await _declare(forge)
    await _import(forge, SUIVI)
    await _import(forge, SUIVI_V2)
    before = await forge.commits()

    deleted = await forge.client.delete(f"{ROUTE}/suivi", timeout=120)
    again = await forge.client.delete(f"{ROUTE}/suivi", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert deleted.status_code == 204, deleted.text
    assert (again.status_code, again.json()["detail"]) == (404, "contrat_inconnu")
    assert listed.json() == []
    for path in ("contract.yaml", "v1.yaml", "v2.yaml"):
        assert await forge.file(f"contracts/suivi/{path}") is None
    assert await forge.commits() == before + 1
    event = await forge.portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = 'contract.deleted'"
    )
    assert event is not None and '"versions": 2' in event["properties"]
