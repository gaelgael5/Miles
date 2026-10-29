from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.signing.keys import generate_keypair

from enrolement.pairing.store_peers import db_upsert_peer
from tests.integration.demandeur_double import RequesterDouble
from tests.integration.enrolement_stack import (
    conclut_appariement,
    demande_appariement,
    open_stack,
    utc_now,
)

pytestmark = pytest.mark.integration

# LA CARDINALITÉ des deux espèces, et ce que la révocation en fait (ticket ba44914b).
#
# Un seul module de paramétrage apparié, N environnements : les deux moitiés se mesurent,
# parce qu'un index unique posé par erreur sur toute la colonne `species` refuserait le
# second environnement — c'est-à-dire toute la raison d'être de ce module — et la faute
# serait verte dans une suite qui n'apparie qu'un environnement à la fois.


async def test_un_second_module_de_parametrage_est_refuse_par_le_modele(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : refusé AU NIVEAU DES DONNÉES, pas seulement de l'écran.

    L'interdit est explicite dans le ticket : « un modèle de données permettant plusieurs
    modules de paramétrage appariés ». Deux appariés, et « qui confie les connexions git »
    n'aurait plus de réponse unique.

    Le refus est éprouvé sur la ROUTE DE PAIR, là où il tombe réellement : l'index unique
    partiel ne parle qu'à la conclusion, et c'est ce mot-là que la stack refusée lira.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        premier = RequesterDouble(origin="http://parametrage-un.test", species="parametrage")
        await demande_appariement(stack, premier)
        await conclut_appariement(stack, premier)

        second = RequesterDouble(origin="http://parametrage-deux.test", species="parametrage")
        await demande_appariement(stack, second)
        code = await stack.client.get("/api/pairing/code", params={"base_url": second.origin})
        assert code.status_code == 200, code.text
        refus = await second.confirm(stack.anonymous(), str(code.json()["code"]))

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "module_de_parametrage_deja_apparie"
        # Un seul apparié, et c'est le PREMIER : le refus ne doit pas avoir remplacé l'un
        # par l'autre en silence.
        apparies = await stack.client.get("/api/pairing/peers")
        assert [p["base_url"] for p in apparies.json()] == [premier.origin]


async def test_plusieurs_environnements_restent_appariables_cote_a_cote(
    blank_db: str, tmp_path: Path
) -> None:
    """L'unicité ne vaut QUE pour le module de paramétrage, et il faut le mesurer.

    Un index unique posé par erreur sur toute la colonne `species` refuserait le second
    environnement — c'est-à-dire toute la raison d'être de ce module. Sans ce test, la
    faute serait verte : la suite d'appariement n'apparie qu'un environnement à la fois.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        for rang in (1, 2):
            double = RequesterDouble(
                origin=f"http://env-{rang}.test", species="environnement", name=f"Env {rang}"
            )
            await demande_appariement(stack, double)
            cree = await stack.client.post(
                "/api/environments", json={"label": f"Env {rang}", "slug": f"env-{rang}"}
            )
            assert cree.status_code == 201, cree.text
            designe = await stack.client.put(
                "/api/pairing/requests/environment",
                params={"base_url": double.origin},
                json={"environment_id": str(cree.json()["id"])},
            )
            assert designe.status_code == 200, designe.text
            await conclut_appariement(stack, double)

        apparies = await stack.client.get("/api/pairing/peers")
        assert len(apparies.json()) == 2


async def test_une_origine_appariee_ne_change_pas_d_espece_en_se_reappariant(
    blank_db: str, tmp_path: Path
) -> None:
    """Un ré-appariement fait tourner des clés ; il ne transforme pas ce qu'une stack est.

    Laisser passer serait le pire des deux : garder l'ancienne espèce ferait confier des
    connexions git à une stack enregistrée comme environnement, et prendre la nouvelle
    libérerait en silence l'environnement qu'elle servait.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://glissante.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)

        # La MÊME origine refrappe en se déclarant environnement.
        double.species = "environnement"
        await demande_appariement(stack, double)
        refus = await stack.client.get("/api/pairing/code", params={"base_url": double.origin})

        # Le refus tombe DEVANT L'HUMAIN, au geste qui accepte. Sans cela il aurait
        # désigné un environnement pour rien, et c'est la stack qui aurait lu le refus
        # trois appels plus tard.
        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "espece_deja_appariee_autrement"
        # L'appariement d'origine est INTACT : ni son espèce ni sa clé n'ont bougé.
        apparies = await stack.client.get("/api/pairing/peers")
        assert [(p["base_url"], p["species"]) for p in apparies.json()] == [
            (double.origin, "parametrage")
        ]


async def test_l_ecriture_du_pair_refuse_elle_aussi_de_changer_d_espece(
    blank_db: str, tmp_path: Path
) -> None:
    """La garde de l'ÉCRITURE, éprouvée pour elle-même, et il faut le faire ici.

    Le refus visible par l'humain est posé plus tôt — au geste qui révèle le code — et il
    rend ce chemin-ci inatteignable par les routes. La clause de conflit reste pourtant la
    seule garde ATOMIQUE : une lecture préalable ne ferme pas la course. Sans ce test, la
    retirer ne ferait rougir personne, et la régression serait verte.

    Éprouvée sur la requête parce que c'est elle qui porte la garde ; la traduction du
    refus en mot lisible, elle, est éprouvée par les tests qui passent par les routes.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://glissante.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)

        refuse = await db_upsert_peer(
            stack.pool,
            double.origin,
            generate_keypair().public_key,
            utc_now(),
            "Stack",
            None,
            double.origin,
            "environnement",
        )

        assert refuse is None
        # Et rien n'a bougé : ni l'espèce, ni la clé.
        garde = await stack.pool.fetchrow(
            "SELECT species, public_key FROM environment_peer WHERE base_url = $1", double.origin
        )
        assert garde["species"] == "parametrage"
        assert garde["public_key"] == double.keypair.public_key


async def test_revoquer_un_module_de_parametrage_detruit_sa_cle_comme_pour_un_environnement(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : la révocation fonctionne comme celle d'un environnement.

    Mesurée par ce qui en découle, et non par le code de retour : la ligne disparaît, la
    clé avec elle, et l'appel signé suivant de cette origine est refusé. L'avis poussé est
    éprouvé par `test_revocation_pg.py`, avec le même code — il ne dépend pas de l'espèce.

    CE QUE CE TEST NE COUVRE PAS, et c'est dit dans le ticket : « elle emporte les
    connexions git confiées ». Rien n'est encore confié — la transmission est le ticket
    voisin edcf78bc, qui dépend de celui-ci —, donc il n'y a rien à emporter et rien à
    éprouver. Le jour où elles existent, c'est ici que le test s'ajoute.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await demande_appariement(stack, double)
        await conclut_appariement(stack, double)
        assert (await double.ping(stack.anonymous())).status_code == 200

        revoque = await stack.client.delete(
            "/api/pairing/peers", params={"base_url": double.origin}
        )

        assert revoque.status_code == 204, revoque.text
        assert (await stack.client.get("/api/pairing/peers")).json() == []
        assert (await double.ping(stack.anonymous())).status_code == 401
        # La clé est DÉTRUITE, pas marquée inactive : plus aucune ligne ne la porte.
        assert await stack.pool.fetchval("SELECT count(*) FROM environment_peer") == 0


async def test_apres_revocation_un_autre_module_de_parametrage_peut_s_apparier(
    blank_db: str, tmp_path: Path
) -> None:
    """L'unicité n'est pas un verrou définitif : révoquer libère la place.

    Sans ce test, un index unique mal posé — sur une colonne qu'une pierre tombale
    garderait — rendrait le remplacement impossible, et le refus serait indiscernable
    d'un second appariement en double.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        premier = RequesterDouble(origin="http://parametrage-un.test", species="parametrage")
        await demande_appariement(stack, premier)
        await conclut_appariement(stack, premier)
        await stack.client.delete("/api/pairing/peers", params={"base_url": premier.origin})

        second = RequesterDouble(origin="http://parametrage-deux.test", species="parametrage")
        await demande_appariement(stack, second)
        await conclut_appariement(stack, second)

        apparies = await stack.client.get("/api/pairing/peers")
        assert [p["base_url"] for p in apparies.json()] == [second.origin]
