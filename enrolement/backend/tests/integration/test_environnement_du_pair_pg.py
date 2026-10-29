from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.protocol import ENVIRONMENT_BODY, PEER_ENVIRONMENT_PATH

from tests.integration.enrolement_stack import EnrolementStack, open_stack
from tests.integration.environnement_double import EnvironmentDouble

pytestmark = pytest.mark.integration

# La route par laquelle un environnement apparié demande à quel environnement du
# référentiel il est rattaché (ticket 2edf1f3c, côté enrôlement).
#
# Cette route LIT une décision prise ici par un humain. L'appelant ne choisit rien et ne
# peut rien choisir : c'est l'invariant que ces tests tiennent, et ils vérifient donc
# surtout contre QUI la route se vérifie, et ce qu'elle refuse de dire à qui n'est pas lui.


async def _cree(stack: EnrolementStack, slug: str) -> str:
    reponse = await stack.client.post(
        "/api/environments", json={"label": f"Environnement {slug}", "slug": slug}
    )
    assert reponse.status_code == 201, reponse.text
    return str(reponse.json()["id"])


async def _code(stack: EnrolementStack, origine: str) -> str:
    reponse = await stack.client.get("/api/pairing/code", params={"base_url": origine})
    assert reponse.status_code == 200, reponse.text
    return str(reponse.json()["code"])


async def _apparie(stack: EnrolementStack, double: EnvironmentDouble, slug: str) -> str:
    """Appariement complet par le protocole, rattaché à un environnement déclaré."""
    environment_id = await _cree(stack, slug)
    async with stack.anonymous() as pair:
        assert (await double.knock(pair)).status_code == 202
        designe = await stack.client.put(
            "/api/pairing/requests/environment",
            params={"base_url": double.origin},
            json={"environment_id": environment_id},
        )
        assert designe.status_code == 200, designe.text
        conclu = await double.confirm(pair, await _code(stack, double.origin))
        assert conclu.status_code == 200, conclu.text
    return environment_id


async def _demande(stack: EnrolementStack, double: EnvironmentDouble) -> Any:
    async with stack.anonymous() as pair:
        return await double.environment(pair)


async def test_un_environnement_apparie_lit_le_sien(blank_db: str, tmp_path: Path) -> None:
    """Le slug et le libellé, les deux noms qui s'affichent à l'autre bout."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")

        reponse = await _demande(stack, double)

        assert reponse.status_code == 200, reponse.text
        assert reponse.json() == {
            "environment": {"slug": "recette", "label": "Environnement recette"}
        }


async def test_l_identifiant_du_referentiel_ne_sort_pas(blank_db: str, tmp_path: Path) -> None:
    """Interdit délibéré : c'est la clé de NOTRE base, et la faire voyager inviterait
    l'autre bout à écrire une relation que personne ne réconcilie."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        environment_id = await _apparie(stack, double, "recette")

        reponse = await _demande(stack, double)

        assert environment_id not in reponse.text
        assert "id" not in reponse.json()["environment"]


async def test_un_appariement_herite_repond_rien_et_non_un_refus(
    blank_db: str, tmp_path: Path
) -> None:
    """Conclu avant que la désignation n'existe : « je n'ai rien décidé pour toi ».

    200 avec `null`, et pas 404 : un 404 se lirait « cette route n'existe pas chez lui »,
    ce qui est exactement ce que son portillon d'authentification rend par ailleurs — et
    l'autre bout replierait sur sa dernière valeur connue au lieu de l'effacer.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await stack.pool.execute(
            "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
            " updated_at, name, contact_url)"
            " VALUES ($1, $2, 'ed25519', now(), now(), 'Hérité', $1)",
            double.origin,
            double.keypair.public_key,
        )

        reponse = await _demande(stack, double)

        assert reponse.status_code == 200, reponse.text
        assert reponse.json() == {"environment": None}


async def test_un_appel_non_signe_est_refuse(blank_db: str, tmp_path: Path) -> None:
    """Fail closed : la route est ouverte au portillon PARCE QU'elle vérifie la signature."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")

        async with stack.anonymous() as pair:
            nu = await pair.post(PEER_ENVIRONMENT_PATH, content=ENVIRONMENT_BODY)

        assert nu.status_code == 401
        assert nu.json()["detail"] == "signature_refusee"


async def test_une_cle_inconnue_sur_la_bonne_origine_est_refusee(
    blank_db: str, tmp_path: Path
) -> None:
    """Le cas qui compte : il ressemble à un appariement valide de tous les côtés sauf
    celui qui décide. Sans cette garde, la route dirait à n'importe qui comment nous
    nommons nos environnements."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")
        imposteur = EnvironmentDouble(origin=double.origin)

        refuse = await _demande(stack, imposteur)

        assert refuse.status_code == 401
        assert refuse.json()["detail"] == "signature_refusee"


async def test_une_origine_jamais_appariee_est_refusee(blank_db: str, tmp_path: Path) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        inconnu = EnvironmentDouble(origin="http://jamais-vu.test")
        await _apparie(stack, double, "recette")

        refuse = await _demande(stack, inconnu)

        assert refuse.status_code == 401
        assert refuse.json()["detail"] == "signature_refusee"


async def test_chacun_ne_lit_que_son_propre_rattachement(blank_db: str, tmp_path: Path) -> None:
    """Deux appariements, deux environnements : la route répond par la clé qui l'a vérifiée.

    C'est la garde qui donne son sens à la vérification : sans elle, un appariement
    apprendrait le rattachement d'un autre.
    """
    une = EnvironmentDouble(origin="http://une.test")
    deux = EnvironmentDouble(origin="http://deux.test")
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, une, "recette")
        await _apparie(stack, deux, "preprod")

        lue, lue2 = await asyncio.gather(_demande(stack, une), _demande(stack, deux))

        assert lue.json()["environment"]["slug"] == "recette"
        assert lue2.json()["environment"]["slug"] == "preprod"


async def test_un_appariement_revoque_ne_lit_plus_rien(blank_db: str, tmp_path: Path) -> None:
    """La révocation détruit sa clé : plus aucune signature de lui n'est vérifiable.

    Et le refus est le MÊME que celui d'une origine jamais appariée, au caractère près :
    les séparer dirait à qui frappe au hasard qu'une origine a été appariée puis révoquée.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double, "recette")
        revoque = await stack.client.delete(
            "/api/pairing/peers", params={"base_url": double.origin}
        )
        assert revoque.status_code == 204, revoque.text

        refuse = await _demande(stack, double)

        assert refuse.status_code == 401
        assert refuse.json()["detail"] == "signature_refusee"


async def test_le_rattachement_change_et_la_route_suit(blank_db: str, tmp_path: Path) -> None:
    """Déplacer l'appariement chez nous change ce que l'autre bout lit, sans réappariement."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")
        preprod = await _cree(stack, "preprod")
        deplace = await stack.client.put(
            "/api/pairing/peers/environment",
            params={"base_url": double.origin},
            json={"environment_id": preprod},
        )
        assert deplace.status_code == 200, deplace.text

        reponse = await _demande(stack, double)

        assert reponse.json()["environment"]["slug"] == "preprod"


async def test_renommer_l_environnement_change_ce_que_le_pair_lit(
    blank_db: str, tmp_path: Path
) -> None:
    """Le libellé et le slug sont RENOMMABLES, et c'est l'état courant qui part.

    Rien n'est figé au moment de l'appariement : si ce l'était, l'autre bout afficherait
    pour toujours un nom que plus personne n'emploie ici.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        environment_id = await _apparie(stack, double, "recette")
        renomme = await stack.client.put(
            f"/api/environments/{environment_id}",
            json={"label": "Recette nord", "slug": "recette-nord"},
        )
        assert renomme.status_code == 200, renomme.text

        reponse = await _demande(stack, double)

        assert reponse.json()["environment"] == {"slug": "recette-nord", "label": "Recette nord"}
