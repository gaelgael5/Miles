"""Les scripts de workflow d'une branche, de bout en bout : la route, le dépôt, le MOTEUR.

Ce que ces tests tiennent et qu'aucun test unitaire ne peut tenir : qu'un workflow créé
par l'écran arrive dans le dépôt sous une forme que `load_directory` du moteur CHARGE
réellement, à côté de l'artefact d'un périmètre ; qu'un script cassé se VOIE dans la liste
au lieu de la faire disparaître ; et qu'il empêche d'enregistrer une version.

Le consommateur de ces fichiers n'est pas Miles : chaque écriture est donc rechargée ici
par `urban_workflow`, et pas seulement comparée à un texte attendu.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from urban_workflow.config import WorkflowsConfig
from urban_workflow.dsl.loader import load_directory
from urban_workflow.dsl.parser import WorkflowScriptParser
from urban_workflow.dsl.visitor import WorkflowConfigVisitor

from miles.datamodels.schema import normalized as normalized_model
from tests.integration.test_domains_pg import add_domain
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/workflows"
MODELES = "/api/workspaces/retrait/data-models"
EVENTS = "/api/workspaces/retrait/workflow-events"
FREEZABLE = "/api/workspaces/retrait/versions/freezable"

COLIS = normalized_model(
    "title: Colis\ntype: object\nproperties:\n  Reference: {type: string}\n",
    "shared",
    "colis",
)


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _create(forge: Forge, name: str, label: str) -> httpx.Response:
    return await forge.client.post(ROUTE, json={"name": name, "label": label}, timeout=120)


async def _declare_event(forge: Forge) -> None:
    """Un type d'event dans le périmètre transverse : c'est ce qu'un workflow INCLUT."""
    written = await forge.client.post(
        MODELES, json={"scope": "shared", "name": "colis", "content": COLIS}, timeout=120
    )
    assert written.status_code in (200, 201), written.text
    declared = await forge.client.post(
        f"{EVENTS}/declarations",
        json={
            "scope": "shared",
            "label": "Colis reçu",
            "slug": "colis_recu",
            "model_scope": "shared",
            "model_name": "colis",
        },
        timeout=120,
    )
    assert declared.status_code == 201, declared.text


async def test_un_workflow_cree_est_un_script_complet_que_le_moteur_relit(forge: Forge) -> None:
    created = await _create(forge, "retrait_comptoir", "Retrait au comptoir")
    assert created.status_code == 201, created.text
    assert created.json() == {
        "name": "retrait_comptoir",
        "label": "Retrait au comptoir",
        "version": None,
        "includes": [],
        "states": 0,
        "problems": [],
    }

    text = await forge.file("workflows/retrait_comptoir.wf")
    assert text is not None
    # Relu par le MOTEUR, pas comparé à un texte : c'est lui qui le chargera.
    parser = WorkflowScriptParser.parse_string(text, "retrait_comptoir.wf")
    assert parser.errors == []
    assert parser.is_fragment is False


async def test_un_workflow_neuf_se_charge_a_cote_de_l_artefact_d_un_perimetre(
    forge: Forge, tmp_path: Path
) -> None:
    """La preuve que la disposition tient : le CHARGEMENT, pas la relecture d'un fichier.

    Les deux fichiers sont rassemblés dans un répertoire PLAT, parce que c'est ce que
    `load_directory` charge et parce qu'un `INCLUDE` désigne un nom de FICHIER. C'est
    aussi ce qui justifie de refuser un workflow portant le nom d'un périmètre : ici, les
    deux fichiers deviendraient le même.
    """
    await _declare_event(forge)
    created = await _create(forge, "retrait_comptoir", "Retrait")
    assert created.status_code == 201, created.text

    artefact = await forge.file("shared/shared.wf")
    assert artefact is not None
    plat = tmp_path / "publie"
    plat.mkdir()
    (plat / "shared.wf").write_text(artefact, encoding="utf-8")
    (plat / "retrait_comptoir.wf").write_text(
        f"INCLUDE 'shared.wf'\n{await forge.file('workflows/retrait_comptoir.wf')}",
        encoding="utf-8",
    )

    config = load_directory(WorkflowsConfig(), WorkflowConfigVisitor, plat, "*.wf")
    # Un seul document chargé : le FRAGMENT n'en est pas un, il alimente celui-ci.
    assert len(config) == 1
    assert [c.name for c in config.get_all("retrait_comptoir")] == ["retrait_comptoir"]


async def test_la_liste_montre_deux_workflows_et_celui_qui_ne_se_relit_pas(forge: Forge) -> None:
    """Deux workflows et des valeurs discriminantes : un seul laisserait passer un écran
    qui ignore la sélection. Et le cassé est SEMÉ hors de Miles — c'est le seul moyen de
    l'obtenir, Miles n'écrivant jamais un script illisible."""
    assert (await _create(forge, "retrait_comptoir", "Retrait au comptoir")).status_code == 201
    await forge.seed(
        {
            "workflows/livraison_domicile.wf": (
                "INCLUDE 'shared.wf'\nNAME livraison_domicile VERSION 2\n"
                "DESCRIPTION 'Livraison à domicile'\nDEFINE STATE attente 'Attente';\n"
            ),
            "workflows/casse.wf": "NAME casse\nDEFINE STATE 'sans clef';\n",
        }
    )

    listed = await forge.client.get(ROUTE, timeout=120)
    assert listed.status_code == 200, listed.text
    par_nom = {item["name"]: item for item in listed.json()}
    assert sorted(par_nom) == ["casse", "livraison_domicile", "retrait_comptoir"]

    # Le lisible garde toutes ses valeurs, et elles diffèrent de celles de l'autre.
    assert par_nom["livraison_domicile"]["version"] == 2
    assert par_nom["livraison_domicile"]["includes"] == ["shared.wf"]
    assert par_nom["livraison_domicile"]["states"] == 1
    assert par_nom["retrait_comptoir"]["version"] is None

    # Le cassé est LÀ, avec ses manquements positionnés, et ne fait pas tomber la liste.
    casse = par_nom["casse"]
    assert casse["label"] is None
    assert casse["problems"], casse
    assert all(p["line"] > 0 for p in casse["problems"])


async def test_un_workflow_nomme_comme_un_perimetre_est_refuse(forge: Forge) -> None:
    """`shared` et un domaine : dans le répertoire plat de la publication, l'artefact du
    périmètre et le workflow deviendraient le même fichier."""
    await add_domain(forge, "livraison")

    for name in ("shared", "livraison"):
        refused = await _create(forge, name, "Peu importe")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == {"field": "nom_de_perimetre"}


@pytest.mark.parametrize("name", ["retrait-comptoir", "Retrait", "retrait comptoir", "2"])
async def test_un_nom_que_le_dsl_ne_sait_pas_ecrire_est_refuse_a_la_saisie(
    forge: Forge, name: str
) -> None:
    """Refusé au geste et non au chargement : le DSL refuse le tiret, les majuscules et
    l'espace, et un script inchargeable posé dans le dépôt casse tout le répertoire."""
    refused = await _create(forge, name, "Retrait")
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == {"field": "name"}


async def test_un_nom_deja_pris_est_refuse_sans_ecraser(forge: Forge) -> None:
    assert (await _create(forge, "retrait_comptoir", "Retrait")).status_code == 201
    again = await _create(forge, "retrait_comptoir", "Autre libellé")
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == "nom_pris"
    # Le premier libellé est intact : un refus n'écrit rien.
    got = await forge.client.get(f"{ROUTE}/retrait_comptoir", timeout=120)
    assert got.json()["label"] == "Retrait"


async def test_on_lit_le_texte_d_un_workflow_et_on_le_supprime(forge: Forge) -> None:
    assert (await _create(forge, "retrait_comptoir", "Retrait")).status_code == 201

    got = await forge.client.get(f"{ROUTE}/retrait_comptoir", timeout=120)
    assert got.status_code == 200, got.text
    assert got.json()["content"].startswith("NAME retrait_comptoir")

    removed = await forge.client.delete(f"{ROUTE}/retrait_comptoir", timeout=120)
    assert removed.status_code == 204, removed.text
    assert (await forge.client.get(ROUTE, timeout=120)).json() == []
    assert await forge.file("workflows/retrait_comptoir.wf") is None

    missing = await forge.client.delete(f"{ROUTE}/retrait_comptoir", timeout=120)
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"] == "workflow_inconnu"


async def test_un_script_casse_empeche_d_enregistrer_une_version(forge: Forge) -> None:
    """La garde qui compte : `load_directory` appelle `check()` sur TOUS les fichiers
    avant d'en visiter un seul, donc un script cassé empêche le chargement des autres."""
    await forge.seed({"workflows/casse.wf": "NAME casse\nDEFINE STATE 'sans clef';\n"})

    freezable = await forge.client.get(FREEZABLE, timeout=180)
    assert freezable.status_code == 200, freezable.text
    reported = {(r["path"], p["code"]) for r in freezable.json()["reports"] for p in r["problems"]}
    assert ("workflows/casse.wf", "script_invalide") in reported


async def test_un_include_introuvable_et_un_nom_qui_ment_sont_rapportes(forge: Forge) -> None:
    """Deux écarts qu'un relecteur humain ne verrait pas, et que le moteur refuse :
    l'`INCLUDE` manquant lève `FileNotFoundError` au chargement, et un `NAME` qui ne
    correspond pas au fichier rend le script introuvable pour qui le cherche."""
    await forge.seed(
        {"workflows/retrait.wf": ("INCLUDE 'absent.wf'\nNAME autre_nom\nDESCRIPTION 'Retrait'\n")}
    )

    freezable = await forge.client.get(FREEZABLE, timeout=180)
    assert freezable.status_code == 200, freezable.text
    reported = {
        (r["path"], p["code"], p["detail"])
        for r in freezable.json()["reports"]
        for p in r["problems"]
    }
    assert ("workflows/retrait.wf", "include_introuvable", "absent.wf") in reported
    assert ("workflows/retrait.wf", "nom_different_du_fichier", "autre_nom") in reported
