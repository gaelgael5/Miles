from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.signing.keys import generate_keypair

from enrolement.pairing.events import PAIRING_CONFIRMED_EVENT, REQUEST_OPENED_EVENT
from enrolement.pairing.store_peers import db_upsert_peer
from tests.integration.demandeur_double import RequesterDouble
from tests.integration.enrolement_stack import EnrolementStack, open_stack, utc_now

pytestmark = pytest.mark.integration

# Deux espèces de demandeur pour un seul mécanisme d'appariement (ticket ba44914b).
#
# Ce qui est éprouvé ici est exactement ce qui DIFFÈRE entre un environnement et le module
# de paramétrage — l'espèce visible, l'unicité du second, l'absence de rattachement — et
# rien de ce qui leur est commun : l'appariement lui-même est éprouvé par
# `test_appariement_pg.py`, avec le même code, et le dupliquer ici prouverait seulement
# qu'on sait recopier un test.


async def _demande(stack: EnrolementStack, double: RequesterDouble) -> dict[str, object]:
    """Frappe, et rend la demande telle que L'ÉCRAN la lira. Jamais une lecture SQL.

    La route est la source de l'écran : c'est elle qui doit porter l'espèce, et un SELECT
    prouverait seulement que la colonne existe.
    """
    frappe = await double.knock(stack.anonymous())
    assert frappe.status_code == 202, frappe.text
    attendues = await stack.client.get("/api/pairing/requests")
    assert attendues.status_code == 200, attendues.text
    lignes = [d for d in attendues.json() if d["base_url"] == double.origin]
    assert len(lignes) == 1
    ligne: dict[str, object] = lignes[0]
    return ligne


async def _apparie(stack: EnrolementStack, double: RequesterDouble) -> None:
    code = await stack.client.get("/api/pairing/code", params={"base_url": double.origin})
    assert code.status_code == 200, code.text
    conclu = await double.confirm(stack.anonymous(), str(code.json()["code"]))
    assert conclu.status_code == 200, conclu.text
    double.expects_public_key = str(conclu.json()["public_key"])


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

        assert (await _demande(stack, parametrage))["species"] == "parametrage"
        assert (await _demande(stack, environnement))["species"] == "environnement"


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

        assert (await _demande(stack, muet))["species"] == "environnement"


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
        await _demande(stack, double)
        await _apparie(stack, double)

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
        demande = await _demande(stack, double)
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
        await _demande(stack, double)
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
        await _demande(stack, double)
        await _apparie(stack, double)
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
        await _demande(stack, premier)
        await _apparie(stack, premier)

        second = RequesterDouble(origin="http://parametrage-deux.test", species="parametrage")
        await _demande(stack, second)
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
            await _demande(stack, double)
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
            await _apparie(stack, double)

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
        await _demande(stack, double)
        await _apparie(stack, double)

        # La MÊME origine refrappe en se déclarant environnement.
        double.species = "environnement"
        await _demande(stack, double)
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
        await _demande(stack, double)
        await _apparie(stack, double)

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


async def test_l_espece_est_rendue_dans_la_liste_des_apparies(
    blank_db: str, tmp_path: Path
) -> None:
    """Seconde moitié du critère 2 : la liste des appariés la dit aussi.

    Une espèce visible seulement à l'acceptation laisserait, un mois plus tard,
    « pourquoi cette stack a-t-elle ces secrets ? » sans réponse lisible à l'écran.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
        await _demande(stack, double)
        await _apparie(stack, double)

        apparies = await stack.client.get("/api/pairing/peers")

        ligne = apparies.json()[0]
        assert ligne["species"] == "parametrage"
        # Et AUCUN environnement : « à rattacher » se lirait comme un geste qui reste à
        # faire, alors qu'il n'y en a pas pour cette espèce.
        assert ligne["environment"] is None


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
        await _demande(stack, double)
        await _apparie(stack, double)
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
        await _demande(stack, premier)
        await _apparie(stack, premier)
        await stack.client.delete("/api/pairing/peers", params={"base_url": premier.origin})

        second = RequesterDouble(origin="http://parametrage-deux.test", species="parametrage")
        await _demande(stack, second)
        await _apparie(stack, second)

        apparies = await stack.client.get("/api/pairing/peers")
        assert [p["base_url"] for p in apparies.json()] == [second.origin]
