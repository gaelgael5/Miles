"""Le contrat d'ingestion s'ouvre SANS COMPTE (Gael, 05/11/2026).

Ce qui ne s'éprouve que là : le portillon de sessions est un middleware, donc ce qu'il
laisse passer ne se lit dans aucun test d'unité du routeur. Et c'est une ouverture
délibérée au monde — la garde qui compte n'est pas qu'elle marche, c'est qu'elle
n'ouvre QUE cela.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from tests.integration.bundles import fabrique_import
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"


async def _ouvert(stack: EnvironnementStack, chemin: str) -> httpx.Response:
    """L'appel d'un intégrateur : aucun cookie, aucune clé."""
    async with stack.anonymous() as anonyme:
        return await anonyme.get(chemin)


@pytest.mark.asyncio
async def test_le_contrat_publie_s_ouvre_sans_session(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await _ouvert(stack, "/api/ingestion/contract")

    assert reponse.status_code == 200, reponse.text
    # Des GABARITS d'adresse : ce contrat vaut pour tout environnement.
    assert "/ingest/{source}/{mode}" in reponse.json()["paths"]


@pytest.mark.asyncio
async def test_le_contrat_d_une_source_servie_s_ouvre_sans_session(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        reponse = await _ouvert(stack, f"/api/ingestion/contract/{SOURCE}")

    assert reponse.status_code == 200, reponse.text
    chemins = reponse.json()["paths"]
    # L'adresse RÉELLE, celle que l'intégrateur appellera, et plus aucun gabarit.
    assert f"/ingest/{SOURCE}/tableau" in chemins
    assert "/ingest/{source}/{mode}" not in chemins


@pytest.mark.asyncio
async def test_une_source_inconnue_est_dite_introuvable(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await _ouvert(stack, "/api/ingestion/contract/jamais-declaree")

    assert reponse.status_code == 404


@pytest.mark.asyncio
async def test_ouvrir_le_contrat_n_ouvre_aucune_autre_route(blank_db: str, tmp_path: Path) -> None:
    # La garde qui compte. Les voisines de la même racine — les méthodes, l'essai, les
    # clés — restent fermées, et l'écriture sur le chemin du contrat aussi.
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as anonyme:
            fermees = {
                "methodes": await anonyme.get("/api/ingestion/methods"),
                "cles": await anonyme.get("/api/api-keys"),
                "stockages": await anonyme.get("/api/storages"),
                "essai": await anonyme.post(f"/api/ingestion/try/{SOURCE}/tableau", content=b"[]"),
                "ecriture": await anonyme.put("/api/ingestion/contract", content=b"{}"),
            }

    assert {nom: r.status_code for nom, r in fermees.items()} == {
        "methodes": 401,
        "cles": 401,
        "stockages": 401,
        "essai": 401,
        "ecriture": 401,
    }
