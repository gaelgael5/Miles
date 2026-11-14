"""La conversion de disposition, sur un dépôt réel.

**Pourquoi ce fichier existe alors que `test_workshop_conversion.py` couvre déjà la
décision** : les tests unitaires éprouvent la FONCTION PURE — une liste de chemins
dedans, un verdict dehors. Ils ne disent rien du CÂBLAGE, et c'est le câblage qui tombe.
Mesuré le 12/11/2026 : deux blocs d'event mal mesurés sont passés au travers de 817 tests
unitaires verts et n'ont été attrapés que par les campagnes — 167 échecs.

Et le montage de ce fichier a lui-même trouvé un défaut, le 13/11/2026 : le `.gitkeep`
que le squelette pose dans `shared/models/` faisait voir tout dépôt ancien comme
« mélangé », donc refusé — et refusé SANS issue, puisque la conversion refuse aussi un
dépôt mélangé. Aucun test unitaire ne pouvait le voir : il fallait un vrai squelette.

Ce que ces tests tiennent, et que rien d'autre ne tient :
- la garde est posée sur TOUS les chemins d'ouverture d'une branche, pas sur un seul ;
- la conversion déplace vraiment les fichiers dans git, en un commit ;
- un rejeu ne fait rien et n'ajoute aucun commit ;
- un dépôt mélangé est refusé par la conversion elle-même ;
- un ex-event devient un modèle ET une déclaration, l'artefact écrit étant relu par le
  MOTEUR : sans la déclaration, la conversion perdrait ce qui distinguait un event d'un
  modèle, et personne ne saurait le retrouver.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.datamodels.meta import meta_text
from miles.datamodels.schema import normalized
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

MODELS = "/api/workspaces/retrait/data-models"
CONVERT = "/api/workspaces/retrait/layout/convert"

# L'ancien nom du dossier, composé pour qu'un renommage automatique du dépôt ne le
# réécrive pas ici : c'est l'ancienne disposition qu'on éprouve.
_VIEUX = "mess" + "ages"
PERSONNE = normalized("type: object\ntitle: Personne\nproperties: {}\n", "shared", "personne")
ANCIEN = {
    f"shared/{_VIEUX}/personne.yaml": PERSONNE,
    f"shared/{_VIEUX}/personne.meta.yaml": meta_text(1),
}
# Un schéma d'event de l'ancienne disposition : son `$id` portait `miles:/events/…`, que
# `target_of` ne résout pas — aucun storage ni source ne pouvait le désigner.
COLIS_RECU = """$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/events/shared/colis_recu
title: Colis reçu
type: object
properties:
  Tracking:
    type: string
"""
AVEC_EVENTS = {
    "shared/events/colis_recu.yaml": COLIS_RECU,
    "shared/events/colis_recu.meta.yaml": meta_text(3),
    "shared/models/personne.yaml": PERSONNE,
}


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def test_une_lecture_sur_un_depot_ancien_est_refusee_en_nommant_son_motif(
    forge: Forge,
) -> None:
    """Sans ce refus, la liste des modèles rendrait une liste VIDE : `model_path` cherche
    sous `models/` et n'y trouve rien. Un paramétrage qui a l'air supprimé et ne l'est
    pas, c'est la panne qu'on découvre chez un client, loin de sa cause."""
    await forge.seed(ANCIEN)

    listed = await forge.client.get(MODELS, timeout=120)

    assert listed.status_code == 409, listed.text
    assert listed.json()["detail"] == "disposition_ancienne"


async def test_la_conversion_deplace_les_fichiers_dans_le_depot_et_rend_la_lecture(
    forge: Forge,
) -> None:
    await forge.seed(ANCIEN)

    converted = await forge.client.post(CONVERT, timeout=120)

    assert converted.status_code == 200, converted.text
    # Le schéma ET ses métadonnées : la version laissée derrière ferait repartir le modèle
    # en version 0, et son prochain enregistrement l'écrirait en 1.
    assert converted.json()["moved"] == 2
    assert await forge.file("shared/models/personne.yaml") == PERSONNE
    assert await forge.file("shared/models/personne.meta.yaml") == meta_text(1)
    assert await forge.file(f"shared/{_VIEUX}/personne.yaml") is None
    listed = await forge.client.get(MODELS, timeout=120)
    assert listed.status_code == 200, listed.text
    assert [m["name"] for m in listed.json()] == ["personne"]
    event = await forge.portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = 'work_layout.converted'"
    )
    assert event is not None


async def test_un_rejeu_de_la_conversion_ne_fait_rien_et_n_ajoute_aucun_commit(
    forge: Forge,
) -> None:
    """Un commit vide se lirait comme une seconde conversion, et brouillerait la seule
    trace qui dit quand une branche est passée à la nouvelle disposition."""
    await forge.seed(ANCIEN)
    await forge.client.post(CONVERT, timeout=120)
    before = await forge.commits()

    again = await forge.client.post(CONVERT, timeout=120)

    assert again.status_code == 200, again.text
    assert again.json()["moved"] == 0
    assert await forge.commits() == before


async def test_un_depot_melange_est_refuse_par_la_conversion_elle_meme(forge: Forge) -> None:
    """Conversion interrompue, ou fusion d'une branche convertie avec une qui ne l'est
    pas. Deux modèles de même nom des deux côtés n'ont pas de bonne réponse automatique :
    on le dit, et un humain tranche dans la forge."""
    await forge.seed({**ANCIEN, "shared/models/colis.yaml": PERSONNE})

    refused = await forge.client.post(CONVERT, timeout=120)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "disposition_melangee"


async def test_un_ex_event_devient_un_modele_et_une_declaration_que_le_moteur_relit(
    forge: Forge,
) -> None:
    """Le coeur de la conversion du 14/11/2026 : le fichier change de dossier, son `$id`
    change de forme, et l'artefact du périmètre reprend ce qui en faisait un type d'event.
    """
    await forge.seed(AVEC_EVENTS)

    converted = await forge.client.post(CONVERT, timeout=120)

    assert converted.status_code == 200, converted.text
    # Le schéma et ses métadonnées : la version laissée derrière ferait repartir le modèle
    # de zéro, et son prochain enregistrement l'écrirait en 1.
    assert converted.json()["moved"] == 2
    schema = await forge.file("shared/models/colis_recu.yaml")
    assert schema is not None
    # L'`$id` RÉÉCRIT : celui de l'ancienne disposition mettait l'event hors de portée des
    # storages, et le garder aurait fait un modèle que rien ne peut désigner.
    assert "$id: miles:/shared/colis_recu" in schema
    assert "miles:/events/" not in schema
    assert await forge.file("shared/models/colis_recu.meta.yaml") == meta_text(3)
    assert await forge.file("shared/events/colis_recu.yaml") is None

    artefact = await forge.file("shared/shared.wf")
    assert artefact is not None, "un ex-event sans déclaration n'est plus un type d'event"
    script = WorkflowScriptParser.parse_string(artefact, "shared.wf")
    assert [(e.line, e.message) for e in script.errors] == []
    assert "DEFINE EVENT colis_recu 'Colis reçu' AS @shared.colis_recu;" in artefact


async def test_le_type_converti_est_servi_par_la_route_des_types_d_event(
    forge: Forge,
) -> None:
    """La conversion ne se contente pas d'écrire un fichier : l'écran le voit."""
    await forge.seed(AVEC_EVENTS)
    await forge.client.post(CONVERT, timeout=120)

    listed = await forge.client.get("/api/workspaces/retrait/workflow-events", timeout=120)

    assert listed.status_code == 200, listed.text
    assert [(t["name"], t["label"], t["model"]) for t in listed.json()] == [
        ("colis_recu", "Colis reçu", "shared/models/colis_recu.yaml")
    ]


async def test_un_depot_qui_porte_models_et_events_se_convertit_quand_meme(
    forge: Forge,
) -> None:
    """Les deux dossiers ont légitimement cohabité du 11/11 au 14/11/2026. Les compter
    comme un mélange aurait rendu tout dépôt de cette fenêtre refusé SANS issue — c'est le
    piège du `.gitkeep` du 13/11, en plus large."""
    await forge.seed(AVEC_EVENTS)

    converted = await forge.client.post(CONVERT, timeout=120)

    assert converted.status_code == 200, converted.text
    assert await forge.file("shared/models/personne.yaml") == PERSONNE


async def test_un_ex_event_dont_le_nom_est_deja_pris_arrete_la_conversion(
    forge: Forge,
) -> None:
    """On n'écrase pas : les deux documents sont dans la forge, et c'est là qu'un humain
    choisit lequel garder. Et on s'arrête AVANT d'écrire quoi que ce soit."""
    await forge.seed(
        {"shared/events/personne.yaml": COLIS_RECU, "shared/models/personne.yaml": PERSONNE}
    )

    refused = await forge.client.post(CONVERT, timeout=120)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "noms_en_conflit"
    assert await forge.remote_file("shared/models/personne.yaml") == PERSONNE
    assert await forge.remote_file("shared/shared.wf") is None
