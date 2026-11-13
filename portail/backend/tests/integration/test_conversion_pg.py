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

Ce que ces quatre tests tiennent, et que rien d'autre ne tient :
- la garde est posée sur TOUS les chemins d'ouverture d'une branche, pas sur un seul ;
- la conversion déplace vraiment les fichiers dans git, en un commit ;
- un rejeu ne fait rien et n'ajoute aucun commit ;
- un dépôt mélangé est refusé par la conversion elle-même.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

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
