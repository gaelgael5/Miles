"""Le référentiel d'événements, de bout en bout : la route, le dépôt, et la frontière.

Ce que ces tests tiennent, et qu'aucun test unitaire ne peut tenir : qu'un événement
écrit par l'écran arrive dans le dépôt sous le chemin et l'`$id` attendus, qu'il ne se
mélange jamais aux modèles de données dans un sens ni dans l'autre, et qu'une version de
branche le valide — c'est-à-dire qu'une arborescence qui en porte un peut encore être gelée.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from miles.datamodels.schema import normalized as normalized_model
from miles.workflowevents.schema import normalized as normalized_event
from tests.integration.test_domains_pg import add_domain
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/workflow-events"
MODELES = "/api/workspaces/retrait/data-models"
FREEZABLE = "/api/workspaces/retrait/versions/freezable"

DOSSIER = normalized_model(
    "title: Dossier\ntype: object\nproperties:\n  reference: {type: string}\n",
    "shared",
    "dossier",
)
AVEC_MODELE = """title: Demande soumise
type: object
required: [Montant]
properties:
  Montant: {type: number}
  Dossier: {$ref: miles:/shared/dossier}
"""


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _declare(forge: Forge, **override: Any) -> httpx.Response:
    body = {"scope": "shared", "label": "Demande soumise", "slug": "demande_soumise"} | override
    return await forge.client.post(f"{ROUTE}/declarations", json=body, timeout=120)


async def _replace(
    forge: Forge, content: str, where: str = "shared/demande_soumise"
) -> httpx.Response:
    return await forge.client.put(f"{ROUTE}/{where}", json={"content": content}, timeout=120)


async def test_un_evenement_declare_est_ecrit_dans_la_branche_puis_relu_et_liste(
    forge: Forge,
) -> None:
    declared = await _declare(forge)
    assert declared.status_code == 201, declared.text
    assert declared.json() == {
        "scope": "shared",
        "name": "demande_soumise",
        "path": "shared/events/demande_soumise.yaml",
        "label": "Demande soumise",
        "version": 1,
        # Déclaré, donc sans champ métier : il ne porte QUE le socle, et la liste le dit.
        "base_only": True,
    }

    written = await forge.file("shared/events/demande_soumise.yaml")
    assert written is not None
    assert "$id: miles:/events/shared/demande_soumise" in written
    assert await forge.file("shared/events/demande_soumise.meta.yaml") == "version: 1\n"

    listed = await forge.client.get(ROUTE, timeout=120)
    assert [e["name"] for e in listed.json()] == ["demande_soumise"]
    read = await forge.client.get(f"{ROUTE}/shared/demande_soumise", timeout=120)
    assert read.json()["content"] == written


async def test_le_schema_remplace_monte_la_version_et_garde_l_id_de_l_evenement(
    forge: Forge,
) -> None:
    await forge.client.post(
        MODELES, json={"scope": "shared", "name": "dossier", "content": DOSSIER}, timeout=120
    )
    await _declare(forge)

    replaced = await _replace(forge, AVEC_MODELE)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["version"] == 2

    written = await forge.file("shared/events/demande_soumise.yaml")
    assert written is not None
    assert "$id: miles:/events/shared/demande_soumise" in written
    assert "$ref: miles:/shared/dossier" in written


async def test_un_evenement_de_domaine_se_range_sous_son_domaine(forge: Forge) -> None:
    await add_domain(forge, "achats")
    declared = await _declare(forge, scope="achats", slug="validation", label="Validation")

    assert declared.status_code == 201, declared.text
    assert declared.json()["path"] == "domains/achats/events/validation.yaml"
    assert await forge.file("domains/achats/events/validation.yaml") is not None


async def test_un_schema_ferme_est_refuse_en_NOMMANT_la_raison(forge: Forge) -> None:
    """Le refus que le moteur aurait prononcé à l'exécution, prononcé à l'écriture."""
    await _declare(forge)

    refused = await _replace(
        forge, "title: D\ntype: object\nadditionalProperties: false\nproperties: {}\n"
    )

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "evenement_non_conforme"
    assert ("additionalProperties", "schema_ferme") in [
        (p["path"], p["code"]) for p in detail["problems"]
    ]


async def test_une_propriete_du_socle_redeclaree_est_refusee(forge: Forge) -> None:
    await _declare(forge)

    refused = await _replace(
        forge, "title: D\ntype: object\nproperties:\n  ExternalId: {type: integer}\n"
    )

    assert refused.status_code == 422, refused.text
    assert [p["code"] for p in refused.json()["detail"]["problems"]] == ["propriete_du_socle"]


async def test_un_nom_que_le_DSL_refuserait_est_refuse_a_la_declaration(forge: Forge) -> None:
    refused = await _declare(forge, slug="demande-soumise")

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == {"field": "name"}


async def test_le_socle_commun_est_servi_en_SCHEMA_depuis_le_moteur_installe(
    forge: Forge,
) -> None:
    """Un JSON Schema, pas une liste de noms : l'écran le monte dans le même éditeur
    visuel que les champs métier, verrouillé, et c'est ce qui montre la dérivation."""
    served = await forge.client.get(f"{ROUTE}/socle", timeout=120)

    assert served.status_code == 200, served.text
    socle = served.json()
    assert socle["type"] == "object"
    assert {"Name", "Uuid", "ExternalId", "CreationDate", "EventDate", "DedupKey"} <= set(
        socle["properties"]
    )
    assert socle["properties"]["IntegrationDate"]["readOnly"] is True
    assert socle["properties"]["Uuid"]["format"] == "uuid"
    assert socle["required"] == ["Name"]


async def test_un_evenement_qui_porte_du_metier_n_est_plus_marque_socle_seul(
    forge: Forge,
) -> None:
    await _declare(forge)
    nu = (await forge.client.get(ROUTE, timeout=120)).json()
    await _replace(forge, "title: D\ntype: object\nproperties:\n  Montant:\n    type: number\n")

    porteur = (await forge.client.get(ROUTE, timeout=120)).json()

    assert [e["base_only"] for e in nu] == [True]
    assert [e["base_only"] for e in porteur] == [False]


async def test_un_evenement_et_un_modele_ne_se_melangent_jamais(forge: Forge) -> None:
    """Les deux sens de la frontière, sur les listes que les écrans consomment."""
    await forge.client.post(
        MODELES, json={"scope": "shared", "name": "dossier", "content": DOSSIER}, timeout=120
    )
    await _declare(forge)

    modeles = await forge.client.get(MODELES, timeout=120)
    evenements = await forge.client.get(ROUTE, timeout=120)

    assert [m["name"] for m in modeles.json()] == ["dossier"]
    assert [e["name"] for e in evenements.json()] == ["demande_soumise"]


async def test_supprimer_un_modele_qu_un_evenement_designe_est_refuse(forge: Forge) -> None:
    """La garde étendue le 11/11/2026 : sans elle, le `$ref` de l'événement ne résoudrait
    plus, et c'est la version de la branche qui l'aurait dit — trop tard, et ailleurs."""
    await forge.client.post(
        MODELES, json={"scope": "shared", "name": "dossier", "content": DOSSIER}, timeout=120
    )
    await _declare(forge)
    await _replace(forge, AVEC_MODELE)

    refused = await forge.client.delete(f"{MODELES}/shared/dossier", timeout=120)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {
        "code": "utilise",
        "by": ["shared/events/demande_soumise.yaml"],
    }


async def test_une_branche_qui_porte_un_evenement_reste_gelable(forge: Forge) -> None:
    """Un événement SANS propriété métier n'est pas un brouillon — à la différence d'un
    modèle. Il ne doit donc pas bloquer une version."""
    await _declare(forge)

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    assert freezable.status_code == 200, freezable.text
    assert freezable.json()["reports"] == []


async def test_un_evenement_retouche_hors_de_miles_bloque_la_version_en_le_nommant(
    forge: Forge,
) -> None:
    """La validation de branche lit les événements du DÉPÔT, pas ce que Miles vient d'écrire.

    Semé hors de Miles avec un `$id` qui ne correspond pas à son emplacement : c'est cet
    URI qui met l'événement hors de portée des storages, et un fichier qui l'a perdu ne
    doit pas pouvoir entrer dans une version.
    """
    await forge.seed(
        {
            "shared/events/autre_evenement.yaml": normalized_event(
                "title: Autre\ntype: object\nproperties: {}\n", "shared", "pas_le_bon_nom"
            )
        }
    )

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    rapports = {r["path"]: [p["code"] for p in r["problems"]] for r in freezable.json()["reports"]}
    assert rapports["shared/events/autre_evenement.yaml"] == ["id_different_du_fichier"]


async def test_aucune_route_des_evenements_n_est_atteignable_sans_session(forge: Forge) -> None:
    """Fail closed : le portillon refuse, et il faut le mesurer route par route."""
    appels = (
        ("GET", ROUTE, None),
        ("GET", f"{ROUTE}/socle", None),
        ("GET", f"{ROUTE}/shared/demande_soumise", None),
        ("POST", f"{ROUTE}/declarations", {"scope": "shared", "label": "D", "slug": "d"}),
        ("PUT", f"{ROUTE}/shared/demande_soumise", {"content": "type: object\n"}),
        ("DELETE", f"{ROUTE}/shared/demande_soumise", None),
    )
    async with forge.portal.anonymous() as visiteur:
        for methode, url, body in appels:
            refused = await visiteur.request(methode, url, json=body, timeout=120)
            assert refused.status_code in (401, 403), f"{methode} {url} -> {refused.status_code}"
