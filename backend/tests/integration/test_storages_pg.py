from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from miles.datamodels.schema import normalized
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/storages"
SOURCES = "/api/workspaces/retrait/sources"
MODELS = "/api/workspaces/retrait/data-models"
CHAINS = "/api/workspaces/retrait/transformations"
ADRESSE = normalized("type: object\nproperties:\n  ville:\n    type: string\n", "shared", "adresse")
SITE = normalized(
    "type: object\nproperties:\n  code:\n    type: string\n"
    "  adresse:\n    $ref: miles:/shared/adresse\n"
    "  enseignes:\n    type: array\n    items:\n      type: string\n",
    "shared",
    "site",
)
STORAGE: dict[str, Any] = {
    "name": "sites",
    "label": "Sites",
    "model": "shared/site",
    "keys": ["$.code"],
    "indexes": [{"name": "par-ville", "columns": ["$.code", "$.adresse.ville"]}],
}


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        for model in (ADRESSE, SITE):
            created = await opened.client.post(MODELS, json=body_of(model), timeout=120)
            assert created.status_code == 201, created.text
        yield opened


async def _declare(forge: Forge, **changes: Any) -> httpx.Response:
    return await forge.client.post(ROUTE, json=STORAGE | changes, timeout=120)


async def test_storage_is_declared_in_git_read_back_and_listed(forge: Forge) -> None:
    """Critère 1 : le cas de Gael — l'objet `site` stocké, avec une propriété pour clé."""
    declared = await _declare(forge)
    read = await forge.client.get(f"{ROUTE}/sites", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert declared.status_code == 201, declared.text
    assert declared.json() == STORAGE | {"rewrite_announced": False}
    assert read.json() == STORAGE
    assert listed.json() == [
        {"name": "sites", "label": "Sites", "model": "shared/site", "keys": ["$.code"]}
    ]
    text = await forge.file("storages/sites.yaml")
    assert text is not None
    assert 'modele: "shared/site"' in text and '- "$.code"' in text


async def test_an_unknown_model_is_refused_by_name(forge: Forge) -> None:
    refused = await _declare(forge, model="shared/inconnu")

    assert [(p["path"], p["code"], p["detail"]) for p in refused.json()["detail"]["problems"]] == [
        ("modele", "modele_inconnu", "shared/inconnu")
    ]


async def test_a_key_must_name_one_scalar_property_of_the_model(forge: Forge) -> None:
    """Critères 3, 4, 5 et 6 : une clé qui ne se compare pas d'une écriture à l'autre."""
    before = await forge.commits()

    empty = await _declare(forge, keys=[])
    not_a_path = await _declare(forge, keys=["$.enseignes[*]"])
    unknown = await _declare(forge, keys=["$.rien"])
    containers = await _declare(forge, keys=["$.enseignes", "$.adresse"])

    assert [(p["path"], p["code"]) for p in empty.json()["detail"]["problems"]] == [
        ("cle", "cle_vide")
    ]
    assert [(p["path"], p["code"]) for p in not_a_path.json()["detail"]["problems"]] == [
        ("cle[0]", "chemin_de_propriete_attendu")
    ]
    assert [(p["path"], p["code"]) for p in unknown.json()["detail"]["problems"]] == [
        ("cle[0]", "propriete_inconnue")
    ]
    assert {(p["path"], p["code"]) for p in containers.json()["detail"]["problems"]} == {
        ("cle[0]", "tableau_interdit"),
        ("cle[1]", "valeur_attendue"),
    }
    assert await forge.commits() == before


async def test_an_index_column_must_resolve_to_a_single_value(forge: Forge) -> None:
    """Critères 7 et 8 : l'unicité de la ligne d'index est le fondement du mécanisme."""
    refused = await _declare(
        forge,
        indexes=[
            {"name": "bancal", "columns": ["$.enseignes", "$.adresse", "$.rien"]},
        ],
    )

    problems = refused.json()["detail"]["problems"]
    assert {(p["path"], p["code"]) for p in problems} == {
        ("index[0].colonnes[0]", "tableau_interdit"),
        ("index[0].colonnes[1]", "valeur_attendue"),
        ("index[0].colonnes[2]", "propriete_inconnue"),
    }
    # La raison est rendue avec le jpath : elle n'est pas évidente pour qui déclare.
    assert {p["detail"] for p in problems} == {"$.enseignes", "$.adresse", "$.rien"}


async def test_many_indexes_of_at_most_three_columns_each(forge: Forge) -> None:
    """Gael, 24/10/2026 : autant d'index que nécessaire, trois colonnes au plus."""
    many = await _declare(
        forge,
        indexes=[
            {"name": "un", "columns": ["$.code"]},
            {"name": "deux", "columns": ["$.code", "$.adresse.ville"]},
            {"name": "trois", "columns": ["$.adresse.ville", "$.code"]},
        ],
    )
    too_many = await _declare(
        forge,
        name="autre",
        indexes=[{"name": "quatre", "columns": ["$.code", "$.adresse.ville", "$.code", "$.rien"]}],
    )

    assert many.status_code == 201, many.text
    # Le plafond est tenu par le contrat d'entrée : 422 avant même la validation métier.
    assert too_many.status_code == 422, too_many.text


async def test_a_doubled_index_name_and_a_doubled_column_are_refused(forge: Forge) -> None:
    """Critère 9, revu : deux index de même nom, et deux fois la même colonne dans un index."""
    same_name = await _declare(
        forge,
        indexes=[
            {"name": "code", "columns": ["$.code"]},
            {"name": "code", "columns": ["$.adresse.ville"]},
        ],
    )
    same_column = await _declare(
        forge, indexes=[{"name": "bancal", "columns": ["$.code", "$.code"]}]
    )

    assert {(p["path"], p["code"]) for p in same_name.json()["detail"]["problems"]} == {
        ("index[0].nom", "nom_double"),
        ("index[1].nom", "nom_double"),
    }
    assert {(p["path"], p["code"]) for p in same_column.json()["detail"]["problems"]} == {
        ("index[0].colonnes[0]", "colonne_doublee"),
        ("index[0].colonnes[1]", "colonne_doublee"),
    }


async def test_a_storage_without_any_index_is_accepted(forge: Forge) -> None:
    """Critère 10 : il reste interrogeable par sa clé."""
    declared = await _declare(forge, indexes=[])

    assert declared.status_code == 201, declared.text


async def test_replay_name_taken_and_modification_that_announces_a_rewrite(forge: Forge) -> None:
    """Critères 11, 12 et 13."""
    await _declare(forge)
    before = await forge.commits()

    replay = await _declare(forge)
    taken = await _declare(forge, keys=["$.adresse.ville"])
    same_shape = await forge.client.put(
        f"{ROUTE}/sites", json=STORAGE | {"keys": ["$.adresse.ville"]}, timeout=120
    )
    fewer_indexes = await forge.client.put(
        f"{ROUTE}/sites",
        json=STORAGE | {"keys": ["$.adresse.ville"], "indexes": []},
        timeout=120,
    )
    renamed = await forge.client.put(f"{ROUTE}/autre", json=STORAGE, timeout=120)

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (taken.status_code, taken.json()["detail"]) == (409, "nom_pris")
    # La clé change, mais ni le modèle ni l'index : rien à réécrire.
    assert same_shape.json()["rewrite_announced"] is False
    assert fewer_indexes.json()["rewrite_announced"] is True
    assert (renamed.status_code, renamed.json()["detail"]) == (409, "nom_fige")
    assert await forge.commits() == before + 2


async def test_a_storage_designated_by_a_source_cannot_be_deleted(forge: Forge) -> None:
    """Critères 14 et 15 : la source cesserait de se vérifier, et l'import casserait loin."""
    await _declare(forge)
    chain = {"label": "Import", "steps": [{"name": "copier", "template": '{ "code": $.code }'}]}
    await forge.client.put(f"{CHAINS}/sites-import", json=chain, timeout=120)
    # Forme du 25/10/2026 : la source est un conteneur, la chaîne vit dans une entrée.
    source = {
        "name": "crm",
        "label": "CRM",
        "storage": "sites",
        "entries": [
            {
                "kind": "web",
                "source_model": "shared/site",
                "chain": "sites-import",
                "modes": {"element": True, "batch": False, "file": False},
                "split": "",
                "unified_transaction": False,
            }
        ],
    }
    declared = await forge.client.post(SOURCES, json=source, timeout=120)
    assert declared.status_code == 201, declared.text

    refused = await forge.client.delete(f"{ROUTE}/sites", timeout=120)
    await forge.client.delete(f"{SOURCES}/crm", timeout=120)
    allowed = await forge.client.delete(f"{ROUTE}/sites", timeout=120)

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        {"code": "storage_utilise", "sources": ["crm"]},
    )
    assert allowed.status_code == 204


async def test_a_version_cannot_freeze_a_storage_broken_outside_miles(forge: Forge) -> None:
    """Critère 18 : retouché dans GitHub, il ne se fige pas si Miles l'aurait refusé."""
    await _declare(forge)
    await forge.publish()
    path = "storages/sites.yaml"
    meta = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}", params={"ref": "back/retrait/edition"}
    )
    text = (await forge.file(path) or "").replace("$.adresse.ville", "$.enseignes")
    changed = await forge.api.put(
        f"/api/v1/repos/miles/{forge.name}/contents/{path}",
        json={
            "branch": "back/retrait/edition",
            "sha": meta.json()["sha"],
            "content": base64.b64encode(text.encode()).decode(),
        },
    )
    assert changed.status_code == 200, changed.text

    refused = await forge.client.post(
        "/api/workspaces/retrait/versions", json={"label": "Storage cassé"}, timeout=120
    )

    assert refused.json()["detail"]["reports"] == [
        {
            "path": path,
            "problems": [
                {
                    "path": "index[0].colonnes[1]",
                    "code": "tableau_interdit",
                    "detail": "$.enseignes",
                }
            ],
        }
    ]
