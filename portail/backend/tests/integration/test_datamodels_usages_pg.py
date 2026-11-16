"""À quoi sert chaque modèle, de bout en bout : la route, le dépôt, les quatre rubriques.

Gael, le 16/11/2026 : « sur les models (event et objets), la façon d'identifier qui fait
quoi m'échappe. » Le défaut a une date — jusqu'au 14/11/2026 le DOSSIER disait le rôle,
`shared/events/` contre `shared/models/` ; depuis que « ce qui fait d'un modèle un type
d'event, c'est qu'un `DEFINE EVENT` le nomme », les deux vivent ensemble.

Ce que ces tests tiennent et qu'aucun test unitaire ne tient : que la lecture croisée part
du DÉPÔT tel que les autres écrans l'ont écrit — un type d'event déclaré par l'écran des
events, un storage déclaré par le sien —, et non d'un texte que le test aurait composé.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from miles.datamodels.schema import normalized
from miles.storages.layout import StorageDoc, storage_path, storage_text
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/data-models"
EVENTS = "/api/workspaces/retrait/workflow-events"
STORAGES = "/api/workspaces/retrait/storages"

COLIS = normalized(
    "title: Colis\ntype: object\nproperties:\n  code:\n    type: string\n", "shared", "colis"
)
ADRESSE = normalized(
    "title: Adresse\ntype: object\nproperties:\n  ville:\n    type: string\n", "shared", "adresse"
)
SITE = normalized(
    "title: Site\ntype: object\nproperties:\n  adresse:\n    $ref: miles:/shared/adresse\n",
    "shared",
    "site",
)
ORPHELIN = normalized(
    "title: Orphelin\ntype: object\nproperties:\n  x:\n    type: string\n", "shared", "orphelin"
)


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _model(forge: Forge, content: str) -> None:
    written = await forge.client.post(ROUTE, json=body_of(content), timeout=120)
    assert written.status_code == 201, written.text


async def _event_type(forge: Forge, **override: Any) -> httpx.Response:
    body = {
        "scope": "shared",
        "label": "Colis reçu",
        "slug": "colis_recu",
        "model_scope": "shared",
        "model_name": "colis",
    } | override
    return await forge.client.post(f"{EVENTS}/declarations", json=body, timeout=120)


async def _storage(forge: Forge, **override: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "name": "sites",
        "label": "Sites",
        "model": "shared/colis",
        "keys": ["$.code"],
        "indexes": [],
        "expiries": [],
    } | override
    return await forge.client.post(STORAGES, json=body, timeout=120)


def _usages(listed: httpx.Response, name: str) -> list[tuple[str, str, str | None]]:
    for model in listed.json()["models"]:
        if model["name"] == name:
            return [(u["kind"], u["name"], u["label"]) for u in model["usages"]]
    raise AssertionError(f"{name} n'est pas dans la liste : {listed.text}")


async def test_un_modele_sert_a_un_type_d_event_ET_a_un_storage_et_la_liste_dit_les_deux(
    forge: Forge,
) -> None:
    """Le cas que la liste séparée interdisait, et qui est réel depuis le 14/11/2026.

    Le type d'event est nommé LUI-MÊME (critère 3) : l'artefact du périmètre seul aurait
    laissé chercher lequel de ses types désigne ce modèle.
    """
    await _model(forge, COLIS)
    declared = await _event_type(forge)
    stored = await _storage(forge)

    listed = await forge.client.get(ROUTE, timeout=120)

    assert (declared.status_code, stored.status_code) == (201, 201), declared.text + stored.text
    assert listed.status_code == 200, listed.text
    assert _usages(listed, "colis") == [
        ("event_type", "colis_recu", "Colis reçu"),
        ("storage", "sites", "Sites"),
    ]
    paths = [u["path"] for u in listed.json()["models"][0]["usages"]]
    assert paths == ["shared/shared.wf", storage_path("sites")]
    assert listed.json()["broken"] == []


async def test_un_modele_designe_par_un_autre_le_sait_et_celui_que_rien_ne_designe_aussi(
    forge: Forge,
) -> None:
    # Discriminant : trois modèles au MÊME emplacement, dont un seul est désigné. Avant le
    # 14/11/2026 le dossier les aurait distingués ; il ne les distingue plus.
    for content in (ADRESSE, SITE, ORPHELIN):
        await _model(forge, content)

    listed = await forge.client.get(ROUTE, timeout=120)

    assert _usages(listed, "adresse") == [("model", "shared/site", "Site")]
    assert _usages(listed, "site") == []
    assert _usages(listed, "orphelin") == []


async def test_un_storage_qui_designe_un_modele_absent_est_rendu_avec_la_liste(
    forge: Forge,
) -> None:
    """Critère 5 : la désignation cassée se voit à l'ouverture de la liste, au lieu de
    n'apparaître qu'au blocage d'une version.

    Semée HORS de Miles, parce que le portail refuse de déclarer un storage sur un modèle
    qu'il ne trouve pas : l'état n'arrive que par une main dans la forge, ou par un modèle
    retiré là-bas. C'est exactement l'état qu'on veut voir dit.
    """
    await _model(forge, COLIS)
    perdu = StorageDoc("comptes", "Comptes", "shared/absent", ("$.code",), (), ())
    await forge.seed({storage_path("comptes"): storage_text(perdu)})

    listed = await forge.client.get(ROUTE, timeout=120)

    assert listed.status_code == 200, listed.text
    assert _usages(listed, "colis") == []
    assert [(b["kind"], b["name"], b["target"]) for b in listed.json()["broken"]] == [
        ("storage", "comptes", "shared/absent")
    ]
