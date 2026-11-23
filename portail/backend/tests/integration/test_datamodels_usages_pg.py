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
from miles_socle.parametrage.chains import chain_path
from miles_socle.parametrage.sources import source_path

from miles.datamodels.schema import normalized
from miles.storages.layout import StorageDoc, storage_path, storage_text
from tests.integration.test_datamodels_pg import body_of
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/data-models"
EVENTS = "/api/workspaces/retrait/workflow-events"
STORAGES = "/api/workspaces/retrait/storages"
SOURCES = "/api/workspaces/retrait/sources"
CHAINS = "/api/workspaces/retrait/transformations"

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
# Le modèle de CE QU'ON REÇOIT : il n'est désigné que par l'entrée d'une source.
BRUT = normalized(
    "title: Brut\ntype: object\nproperties:\n  accountId:\n    type: string\n", "shared", "brut"
)
# Même propriété que `COLIS`, pour qu'un storage puisse passer de l'un à l'autre sans que
# ses clés deviennent le sujet du test.
AUTRE = normalized(
    "title: Autre\ntype: object\nproperties:\n  code:\n    type: string\n", "shared", "autre"
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


async def _chain(forge: Forge, slug: str = "comptes-import", **override: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "label": "Import",
        "steps": [{"name": "copier", "template": '{ "code": $.code }'}],
    } | override
    return await forge.client.put(f"{CHAINS}/{slug}", json=body, timeout=120)


async def _source(forge: Forge, **override: Any) -> httpx.Response:
    entry: dict[str, Any] = {
        "kind": "web",
        "source_model": "shared/brut",
        "chain": "comptes-import",
        "modes": {"element": True, "batch": True, "file": True},
        "split": "$.accounts[*]",
        "unified_transaction": False,
        "write_batch": 100,
        "missing_removed_after_days": None,
    }
    body: dict[str, Any] = {
        "name": "comptes",
        "label": "Comptes",
        "storage": "sites",
        "entries": [entry],
    } | override
    return await forge.client.post(SOURCES, json=body, timeout=120)


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

    L'ORDRE compte depuis le 22/11/2026 (story `7b4f7a32`) : un storage ne peut plus être
    déclaré SUR un payload de type d'event. L'inverse reste permis, et c'est l'arbitrage de
    Gael du même jour — une désignation déjà posée est signalée, jamais cassée. Ce test
    éprouve donc ce qui subsiste, et c'est le cas qui compte : la liste doit nommer les DEUX
    natures d'un modèle qu'un storage projetait avant qu'un event n'en fasse son payload.
    """
    await _model(forge, COLIS)
    stored = await _storage(forge)
    declared = await _event_type(forge)

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


# --- Le refus de supprimer couvre-t-il les mêmes natures que la liste ? (bug `6ed86d6b`) -
# Trois tests et non un seul, par décision du ticket : les trois natures manquaient à la
# même liste, et rien ne garantit qu'elles se corrigent ensemble. Ils sont ICI, avec la
# lecture qu'ils doivent faire coïncider — pas dans `test_datamodels_pg.py`, qui éprouve le
# geste de suppression lui-même.


async def test_supprimer_un_modele_qu_un_storage_projette_est_refuse(forge: Forge) -> None:
    """Jusqu'au 23/11/2026 la suppression partait en `204`, et le storage désignait un
    modèle absent : l'incohérence ne se disait qu'à l'ouverture de l'écran de figement,
    depuis un autre écran et après que le commit de suppression était parti.
    """
    await _model(forge, COLIS)
    stored = await _storage(forge)

    refused = await forge.client.delete(f"{ROUTE}/shared/colis", timeout=120)
    toujours_la = await forge.client.get(f"{ROUTE}/shared/colis", timeout=120)

    assert stored.status_code == 201, stored.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "utilise", "by": [storage_path("sites")]}
    assert toujours_la.status_code == 200, toujours_la.text


async def test_supprimer_un_modele_qu_une_entree_de_source_designe_est_refuse(
    forge: Forge,
) -> None:
    await _model(forge, COLIS)
    await _model(forge, BRUT)
    await _storage(forge)
    await _chain(forge)
    declared = await _source(forge)

    refused = await forge.client.delete(f"{ROUTE}/shared/brut", timeout=120)
    toujours_la = await forge.client.get(f"{ROUTE}/shared/brut", timeout=120)

    assert declared.status_code == 201, declared.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "utilise", "by": [source_path("comptes")]}
    assert toujours_la.status_code == 200, toujours_la.text


async def test_supprimer_un_modele_qu_une_etape_de_chaine_lit_est_refuse(forge: Forge) -> None:
    await _model(forge, ADRESSE)
    saved = await _chain(
        forge,
        steps=[
            {
                "name": "copier",
                "template": '{ "ville": $.ville }',
                "source_model": "miles:/shared/adresse",
            }
        ],
    )

    refused = await forge.client.delete(f"{ROUTE}/shared/adresse", timeout=120)
    toujours_la = await forge.client.get(f"{ROUTE}/shared/adresse", timeout=120)

    assert saved.status_code in (200, 201), saved.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "utilise", "by": [chain_path("comptes-import")]}
    assert toujours_la.status_code == 200, toujours_la.text


async def test_ce_qui_ne_designe_plus_ne_bloque_pas_la_suppression(forge: Forge) -> None:
    """Le refus élargi ne doit pas devenir un verrou (critère 4 du bug `6ed86d6b`).

    Discriminant : le storage EXISTE toujours, il projette un AUTRE modèle. Le supprimer
    aurait aussi fait passer ce test, sans éprouver que le refus relit l'état de la branche
    au lieu de se souvenir d'une désignation passée.
    """
    for content in (COLIS, AUTRE, ORPHELIN):
        await _model(forge, content)
    await _storage(forge)
    deplace = await forge.client.put(
        f"{STORAGES}/sites",
        json={
            "name": "sites",
            "label": "Sites",
            "model": "shared/autre",
            "keys": ["$.code"],
            "indexes": [],
            "expiries": [],
        },
        timeout=120,
    )

    libere = await forge.client.delete(f"{ROUTE}/shared/colis", timeout=120)
    jamais_designe = await forge.client.delete(f"{ROUTE}/shared/orphelin", timeout=120)

    assert deplace.status_code == 200, deplace.text
    assert libere.status_code == 204, libere.text
    assert jamais_designe.status_code == 204, jamais_designe.text
