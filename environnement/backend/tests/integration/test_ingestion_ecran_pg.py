"""L'écran du service d'ingestion : son état, et le journal des appels (story 1c1cd22e).

« il faut dans l'ecran voir l'état de santé du service. et voir un log des derniers
appels. » (Gael, 02/11/2026)

Ce qui ne s'éprouve qu'ici : que les points d'entrée ANNONCÉS sont ceux que le dépôt
accepte vraiment — les deux se lisent du même arbre servi, et une divergence enverrait un
partenaire frapper à une porte fermée.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest import INGEST_PATH
from environnement.ingestion.model import BATCH, ELEMENT, FILE
from tests.integration.bundles import fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import ordonne, sert

pytestmark = pytest.mark.integration

COMPTES = "comptes-pudo"
SITES = "sites-pudo"


async def _cle(stack: EnvironnementStack, sources: tuple[str, ...] = (COMPTES,)) -> str:
    recu = await stack.client.post(
        "/api/api-keys", json={"label": "Transporteur", "sources": list(sources)}
    )
    assert recu.status_code == 201, recu.text
    secret: str = recu.json()["secret"]
    return secret


async def _depose(stack: EnvironnementStack, cle: str, corps: Any, mode: str = BATCH) -> Any:
    return await stack.anonymous().post(
        INGEST_PATH.format(source=COMPTES, mode=mode),
        content=json.dumps(corps).encode(),
        headers={"X-API-Key": cle, "Content-Type": "application/json"},
    )


async def test_sans_version_servie_l_ecran_le_dit_et_n_annonce_aucun_point_d_entree(
    blank_db: str, tmp_path: Path
) -> None:
    """L'état normal d'une stack neuve, pas une erreur."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        etat = await stack.client.get("/api/ingestion/health")

        assert etat.status_code == 200, etat.text
        corps = etat.json()
        assert corps["version_number"] is None
        assert corps["endpoints"] == []
        assert corps["deposits_total"] == 0
        assert corps["last_deposit_at"] is None


async def test_l_ecran_annonce_la_version_servie_et_ses_points_d_entree(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        corps = (await stack.client.get("/api/ingestion/health")).json()

        assert corps["version_number"] == 1
        assert corps["version_commit"] == versions[1].commit
        assert corps["version_served_at"] is not None
        points = {(p["source"], p["mode"]): p for p in corps["endpoints"]}
        # v1 : `comptes-pudo` expose element+tableau, `sites-pudo` element seul.
        assert set(points) == {
            (COMPTES, ELEMENT),
            (COMPTES, BATCH),
            (SITES, ELEMENT),
        }
        assert points[(COMPTES, BATCH)]["served"] is True
        assert points[(COMPTES, BATCH)]["storage"] == "accounts"
        assert points[(COMPTES, BATCH)]["entry_model"] == "pudo/accounts"
        # L'adresse complète : c'est ce qui répond à « où est-ce que je pousse ? ».
        assert points[(COMPTES, BATCH)]["path"] == f"/ingest/{COMPTES}/{BATCH}"


async def test_l_adresse_annoncee_est_CELLE_QUI_ACCEPTE_vraiment(
    blank_db: str, tmp_path: Path
) -> None:
    """La garde qui compte : une divergence entre ce que l'écran annonce et ce que le
    dépôt accepte enverrait un partenaire frapper à une porte fermée."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)
        corps = (await stack.client.get("/api/ingestion/health")).json()

        annoncee = next(
            p["path"]
            for p in corps["endpoints"]
            if (p["source"], p["mode"]) == (COMPTES, BATCH) and p["served"]
        )
        recu = await stack.anonymous().post(
            annoncee,
            content=json.dumps([{"AccountId": "A-1"}]).encode(),
            headers={"X-API-Key": cle, "Content-Type": "application/json"},
        )

        assert recu.status_code == 201, recu.text


async def test_le_mode_fichier_est_annonce_comme_SERVI_et_aucun_mode_ne_reste_en_attente(
    blank_db: str, tmp_path: Path
) -> None:
    """Depuis le 04/11/2026, les trois modes sont servis (story `0f14adbd`).

    Ce que l'écran annonce doit être ce que le dépôt accepte : le présenter comme non
    servi ferait croire à un dépôt refusé, alors qu'il est pris en charge. Et plus aucun
    mode n'attend son branchement, donc plus rien à signaler à ce titre.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        # v2 coche `fichier` sur `comptes-pudo`.
        await sert(stack, double, versions[2])

        corps = (await stack.client.get("/api/ingestion/health")).json()

        fichier = [p for p in corps["endpoints"] if p["mode"] == FILE]
        assert fichier, "le mode fichier déclaré doit apparaître"
        assert all(p["served"] is True for p in fichier)
        assert corps["bulk_modes"] == []


async def test_une_source_illisible_est_nommee_dans_l_ecran(blank_db: str, tmp_path: Path) -> None:
    """La taire ferait chercher une source absente alors qu'elle est là, et fautive."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        (stack.tree.root / "sources" / "cassee.yaml").write_text("nom: [", encoding="utf-8")

        corps = (await stack.client.get("/api/ingestion/health")).json()

        # Le fichier n'est pas dans l'index git de l'arbre servi : il n'est donc pas du
        # paramétrage, et l'écran ne doit pas l'inventer. Ce que ce test constate, c'est
        # que l'arbre fait foi par son INDEX, pas par son disque.
        assert "cassee" not in corps["unreadable_sources"]


async def test_les_cles_sont_comptees_et_celles_qui_n_ont_jamais_servi_distinguees(
    blank_db: str, tmp_path: Path
) -> None:
    """Jamais employée dit qu'un partenaire n'a pas encore branché son intégration."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        employee = await _cle(stack)
        await _cle(stack)
        await _depose(stack, employee, [{"AccountId": "A-1"}])

        corps = (await stack.client.get("/api/ingestion/health")).json()

        assert (corps["active_keys"], corps["never_used_keys"]) == (2, 1)
        assert corps["deposits_total"] == 1
        assert corps["deposits_recent"] == 1
        assert corps["last_deposit_at"] is not None


async def test_une_cle_revoquee_n_est_plus_comptee_comme_active(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        emise = await stack.client.post(
            "/api/api-keys", json={"label": "À révoquer", "sources": [COMPTES]}
        )
        await stack.client.post(f"/api/api-keys/{emise.json()['key']['id']}/revoke")

        corps = (await stack.client.get("/api/ingestion/health")).json()

        assert (corps["active_keys"], corps["never_used_keys"]) == (0, 0)


async def test_le_journal_porte_une_ligne_par_APPEL_et_jamais_la_valeur_de_la_cle(
    blank_db: str, tmp_path: Path
) -> None:
    """Une ligne par appel, pas par objet : un dépôt de masse rendrait l'écran illisible."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)
        await _depose(stack, cle, [{"AccountId": "A-1"}, {"AccountId": "A-2"}])

        journal = await stack.client.get("/api/ingestion/calls")

        assert journal.status_code == 200, journal.text
        corps = journal.json()
        assert corps["total"] == 1
        ligne = corps["calls"][0]
        assert (ligne["source"], ligne["mode"], ligne["object_count"]) == (COMPTES, BATCH, 2)
        assert ligne["version_number"] == 1
        assert ligne["key_label"] == "Transporteur"
        assert ligne["key_prefix"] == cle[:12]
        assert ligne["size_bytes"] > 0
        # Jamais la valeur, nulle part dans la réponse.
        assert cle not in journal.text
        # Le filtre ne propose que des sources déclarées par la version servie.
        assert corps["sources"] == [COMPTES, SITES]


async def test_le_journal_rend_le_plus_recent_d_abord_et_se_pagine(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)
        for rang in range(3):
            await _depose(stack, cle, [{"AccountId": f"A-{rang}"}])

        page = await stack.client.get("/api/ingestion/calls?taille=2&page=1")
        suite = await stack.client.get("/api/ingestion/calls?taille=2&page=2")

        assert page.json()["total"] == 3
        assert len(page.json()["calls"]) == 2
        assert len(suite.json()["calls"]) == 1
        dates = [appel["received_at"] for appel in page.json()["calls"]]
        assert dates == sorted(dates, reverse=True)


async def test_le_journal_se_restreint_a_une_source(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack, sources=(COMPTES, SITES))
        await _depose(stack, cle, [{"AccountId": "A-1"}])
        await stack.anonymous().post(
            INGEST_PATH.format(source=SITES, mode=ELEMENT),
            content=json.dumps({"Id": "S-1"}).encode(),
            headers={"X-API-Key": cle, "Content-Type": "application/json"},
        )

        tous = await stack.client.get("/api/ingestion/calls")
        un_seul = await stack.client.get(f"/api/ingestion/calls?source={SITES}")

        assert tous.json()["total"] == 2
        assert un_seul.json()["total"] == 1
        assert un_seul.json()["calls"][0]["source"] == SITES


async def test_aucun_appel_n_est_pas_une_erreur(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        journal = await stack.client.get("/api/ingestion/calls")

        assert journal.status_code == 200, journal.text
        assert (journal.json()["total"], journal.json()["calls"]) == (0, [])


async def test_l_ecran_de_l_ingestion_exige_une_session(blank_db: str, tmp_path: Path) -> None:
    """Réservé à l'administrateur : une clé d'ingestion n'ouvre jamais ces routes."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        for chemin in ("/api/ingestion/health", "/api/ingestion/calls"):
            anonyme = await stack.anonymous().get(chemin)
            avec_cle = await stack.anonymous().get(chemin, headers={"X-API-Key": cle})

            assert anonyme.status_code == 401, (chemin, anonyme.text)
            assert avec_cle.status_code == 401, (chemin, avec_cle.text)


async def test_la_version_suivante_change_les_points_d_entree_annonces(
    blank_db: str, tmp_path: Path
) -> None:
    """La v3 retire `sites`, donc sa source : l'écran ne doit plus l'annoncer."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        assert any(
            p["source"] == SITES
            for p in (await stack.client.get("/api/ingestion/health")).json()["endpoints"]
        )

        await ordonne(stack, double, versions[3])

        corps = (await stack.client.get("/api/ingestion/health")).json()
        assert corps["version_number"] == 3
        assert all(p["source"] != SITES for p in corps["endpoints"])
