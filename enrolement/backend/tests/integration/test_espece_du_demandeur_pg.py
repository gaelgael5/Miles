from __future__ import annotations

from pathlib import Path

import pytest

from enrolement.pairing.events import PAIRING_CONFIRMED_EVENT, REQUEST_OPENED_EVENT
from tests.integration.demandeur_double import RequesterDouble
from tests.integration.enrolement_stack import (
    conclut_appariement,
    demande_appariement,
    open_stack,
)

pytestmark = pytest.mark.integration

# L'ESPÈCE du demandeur : ce qu'elle dit, où elle se lit, et ce qu'elle change au parcours
# (ticket ba44914b). Sa CARDINALITÉ — un seul module de paramétrage, N environnements — et
# la révocation sont dans `test_cardinalite_du_parametrage_pg.py`.
#
# Ce qui est éprouvé ici est exactement ce qui DIFFÈRE entre un environnement et le module
# de paramétrage, et rien de ce qui leur est commun : l'appariement lui-même est éprouvé
# par `test_appariement_pg.py`, avec le même code, et le dupliquer prouverait seulement
# qu'on sait recopier un test.


async def test_l_espece_declaree_est_rendue_a_l_ecran_des_demandes(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2 : l'humain qui accepte doit savoir ce qu'il accepte.

    Les conséquences ne sont pas les mêmes — un environnement reçoit des devices, le
    module de paramétrage se fait confier des connexions git —, et rien d'autre dans la
    ligne ne les distingue : le nom déclaré vient d'un inconnu, l'URL ne dit rien.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        parametrage = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        environnement = RequesterDouble(origin="http://env.test", species="environnement")

        assert (await demande_appariement(stack, parametrage))["species"] == "parametrage"
        assert (await demande_appariement(stack, environnement))["species"] == "environnement"


async def test_une_demande_sans_espece_declaree_est_lue_comme_un_environnement(
    blank_db: str, tmp_path: Path
) -> None:
    """Le champ est FACULTATIF, et son absence a un sens exact — pas un repli de confort.

    Avant le 29/10/2026, un environnement était la seule espèce qui pût frapper : une
    demande qui ne déclare rien vient donc d'un demandeur d'avant l'espèce, et c'est la
    seule valeur qui soit vraie pour elle. Sans cette lecture, le champ ajouté au contrat
    aurait fait refuser en 422 des demandes que ce module sait parfaitement lire.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        muet = RequesterDouble(origin="http://ancien.test")
        assert muet.knock_body().find(b"species") == -1

        assert (await demande_appariement(stack, muet))["species"] == "environnement"


async def test_l_espece_est_au_journal_de_la_demande_et_de_la_conclusion(
    blank_db: str, tmp_path: Path
) -> None:
    """Le jour où une stack a reçu ce qu'elle n'aurait pas dû, c'est ce qu'on viendra lire.

    Aux DEUX moments, parce que ce sont deux faits : ce qui a été demandé, et ce qui a été
    conclu. Un seul des deux laisserait « sous quelle espèce avait-elle frappé ? » sans
    réponse quand la demande a disparu.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)

        especes = await stack.pool.fetch(
            "SELECT type, properties->>'species' AS species FROM events"
            " WHERE type = ANY($1::text[]) ORDER BY written_at",
            [REQUEST_OPENED_EVENT, PAIRING_CONFIRMED_EVENT],
        )

        assert [(r["type"], r["species"]) for r in especes] == [
            (REQUEST_OPENED_EVENT, "parametrage"),
            (PAIRING_CONFIRMED_EVENT, "parametrage"),
        ]


async def test_le_code_d_un_module_de_parametrage_est_revelable_sans_designation(
    blank_db: str, tmp_path: Path
) -> None:
    """Il ne reçoit pas de devices : il n'y a rien à lui désigner.

    Exiger la même désignation que d'un environnement rendrait son appariement
    IMPOSSIBLE — le code ne serait jamais révélable, et l'écran afficherait un refus dont
    le remède n'existe pas.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        demande = await demande_appariement(stack, double)
        assert demande["environment"] is None

        code = await stack.client.get("/api/pairing/code", params={"base_url": double.origin})

        assert code.status_code == 200, code.text


async def test_designer_un_environnement_a_un_module_de_parametrage_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Refus NOMMÉ, et non une contrainte de base : le geste n'a pas de sens pour lui.

    Le laisser passer CONSOMMERAIT — par l'unicité de `environment_id` — un environnement
    du référentiel qu'aucune stack ne servirait jamais.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await demande_appariement(stack, double)
        cree = await stack.client.post(
            "/api/environments", json={"label": "Environnement de recette", "slug": "recette"}
        )
        assert cree.status_code == 201, cree.text

        refus = await stack.client.put(
            "/api/pairing/requests/environment",
            params={"base_url": double.origin},
            json={"environment_id": str(cree.json()["id"])},
        )

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "espece_sans_environnement"
        # L'environnement est resté LIBRE : c'est ce que le refus protège, et une
        # assertion sur le seul code de retour ne le dirait pas.
        liste = await stack.client.get("/api/environments")
        assert [e["designated_base_url"] for e in liste.json()] == [None]


async def test_rattacher_un_environnement_a_un_module_de_parametrage_apparie_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Même règle sur l'appariement CONCLU : les deux chemins d'écriture sont gardés.

    Un seul des deux gardé laisserait l'autre poser la désignation, et le refus viendrait
    alors de la contrainte `environment_peer_environnement_seul_rattache` — juste, mais
    muette sur ce qu'il faut faire.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)
        cree = await stack.client.post(
            "/api/environments", json={"label": "Environnement de recette", "slug": "recette"}
        )
        assert cree.status_code == 201, cree.text

        refus = await stack.client.put(
            "/api/pairing/peers/environment",
            params={"base_url": double.origin},
            json={"environment_id": str(cree.json()["id"])},
        )

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "espece_sans_environnement"


async def test_l_espece_est_rendue_dans_la_liste_des_apparies(
    blank_db: str, tmp_path: Path
) -> None:
    """Seconde moitié du critère 2 : la liste des appariés la dit aussi.

    Une espèce visible seulement à l'acceptation laisserait, un mois plus tard,
    « pourquoi cette stack a-t-elle ces secrets ? » sans réponse lisible à l'écran.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)

        apparies = await stack.client.get("/api/pairing/peers")

        ligne = apparies.json()[0]
        assert ligne["species"] == "parametrage"
        # Et AUCUN environnement : « à rattacher » se lirait comme un geste qui reste à
        # faire, alors qu'il n'y en a pas pour cette espèce.
        assert ligne["environment"] is None
