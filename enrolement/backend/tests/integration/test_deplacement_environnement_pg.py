from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.keys import generate_keypair

from enrolement.pairing import environment_link
from enrolement.pairing.model import (
    ENVIRONMENT_ATTACHED_EVENT,
    ENVIRONMENT_MOVED_EVENT,
)
from tests.integration.enrolement_stack import EnrolementStack, open_stack

pytestmark = pytest.mark.integration

# Changer l'environnement d'un appariement CONCLU, tant qu'il ne porte aucun device
# (ticket 8803f092, arbitrage de Gael du 29/10/2026, qui renverse la règle « révoquer puis
# réapparier » du ticket bf2115cd).
#
# Les appariements sont posés au niveau des données plutôt que conclus par le protocole :
# ce qui est éprouvé ici est le DÉPLACEMENT, et refaire à chaque test un appariement
# complet — frapper, désigner, révéler le code, confirmer — n'ajouterait aucune garde et
# ferait dépendre ces tests de pannes qui ne les concernent pas. Le protocole lui-même est
# éprouvé par `test_appariement_pg.py`.


async def _pose_apparie(stack: EnrolementStack, origine: str, environment_id: str | None) -> None:
    await stack.pool.execute(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, name, environment_id, contact_url)"
        " VALUES ($1, $2, 'ed25519', now(), now(), 'Stack', $3::uuid, $1)",
        origine,
        generate_keypair().public_key,
        environment_id,
    )


async def _cree(stack: EnrolementStack, slug: str) -> str:
    reponse = await stack.client.post(
        "/api/environments", json={"label": f"Environnement {slug}", "slug": slug}
    )
    assert reponse.status_code == 201, reponse.text
    return str(reponse.json()["id"])


async def _change(stack: EnrolementStack, origine: str, environment_id: str) -> Any:
    return await stack.client.put(
        "/api/pairing/peers/environment",
        params={"base_url": origine},
        json={"environment_id": environment_id},
    )


async def _pair(stack: EnrolementStack, origine: str) -> dict[str, Any]:
    apparies = await stack.client.get("/api/pairing/peers")
    return next(p for p in apparies.json() if p["base_url"] == origine)


async def _environnement(stack: EnrolementStack, environment_id: str) -> dict[str, Any]:
    declares = await stack.client.get("/api/environments")
    return next(e for e in declares.json() if e["id"] == environment_id)


async def _events(stack: EnrolementStack, type_event: str) -> list[dict[str, Any]]:
    lignes = await stack.pool.fetch(
        "SELECT properties, author_directory, author_subject FROM events WHERE type = $1",
        type_event,
    )
    return [
        # `jsonb` revient en CHAÎNE : asyncpg ne décode pas sans codec, et comparer des
        # clefs sur la chaîne comparerait ses caractères (mesuré le 28/10/2026).
        {**json.loads(ligne["properties"]), "_auteur": ligne["author_subject"]}
        for ligne in lignes
    ]


async def test_un_appariement_sans_device_change_d_environnement(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : sans device, le changement est une correction de saisie."""
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        pris = await _cree(stack, "preprod")
        await _pose_apparie(stack, "http://stack.test", quitte)

        reponse = await _change(stack, "http://stack.test", pris)

        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["environment"]["id"] == pris
        assert (await _pair(stack, "http://stack.test"))["environment"]["id"] == pris


async def test_le_deplacement_ecrit_qui_a_decide_et_les_deux_environnements(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : l'event porte l'appariement, l'environnement quitté et celui qui est pris.

    Et il porte un type À LUI : c'est sous le mot « déplacé » qu'on relira ce journal le
    jour où des devices n'arrivent pas où on les attendait, jamais sous « le champ a changé ».
    """
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        pris = await _cree(stack, "preprod")
        await _pose_apparie(stack, "http://stack.test", quitte)

        await _change(stack, "http://stack.test", pris)

        deplacements = await _events(stack, ENVIRONMENT_MOVED_EVENT)
        assert len(deplacements) == 1
        event = deplacements[0]
        assert event["environment_id"] == pris
        assert event["previous_environment_id"] == quitte
        # Les deux noms du moment, en plus des identifiants : relire le journal dans un an
        # se fait sous le nom qu'on employait alors, et les deux sont renommables.
        assert event["previous_environment_slug"] == "recette"
        assert event["previous_environment_label"] == "Environnement recette"
        assert event["environment_slug"] == "preprod"
        # L'identité (annuaire, sub) et jamais la personne.
        assert event["_auteur"] != ""
        # Et SURTOUT pas un rattachement : les deux gestes ne se cherchent pas ensemble.
        assert await _events(stack, ENVIRONMENT_ATTACHED_EVENT) == []


async def test_un_rattachement_n_ecrit_pas_un_deplacement(blank_db: str, tmp_path: Path) -> None:
    """La réciproque, et elle n'est pas symétrique : il n'y avait rien à quitter.

    Les champs `previous_*` sont ABSENTS, et non nuls : une désignation qui porterait
    `previous_environment_id: null` ferait chercher un déplacement qui n'a pas eu lieu.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        pris = await _cree(stack, "recette")
        await _pose_apparie(stack, "http://herite.test", None)

        assert (await _change(stack, "http://herite.test", pris)).status_code == 200

        rattachements = await _events(stack, ENVIRONMENT_ATTACHED_EVENT)
        assert len(rattachements) == 1
        assert "previous_environment_id" not in rattachements[0]
        assert await _events(stack, ENVIRONMENT_MOVED_EVENT) == []


async def test_un_appariement_qui_porte_des_devices_refuse_de_changer(
    blank_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critère 2, et la SEULE façon d'éprouver cette garde aujourd'hui.

    Le référentiel des devices n'existe pas : `db_count_peer_devices` rend zéro partout, et
    la garde ne mord donc sur rien en vrai. On lui injecte un compte non nul pour vérifier
    qu'elle mord — sans quoi on livrerait une garde dont personne n'a vu l'effet, et c'est
    ce point précis qu'on rebranchera sur le parc.
    """

    async def _trois(_db: Any, _base_url: str) -> int:
        return 3

    monkeypatch.setattr(environment_link, "db_count_peer_devices", _trois)
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        pris = await _cree(stack, "preprod")
        await _pose_apparie(stack, "http://stack.test", quitte)

        reponse = await _change(stack, "http://stack.test", pris)

        assert reponse.status_code == 409
        # Un refus NOMMÉ, qui renvoie vers le déplacement en bloc des devices : un message
        # générique enverrait chercher du côté des droits ou du réseau.
        assert reponse.json()["detail"] == "appariement_porte_des_devices"
        assert (await _pair(stack, "http://stack.test"))["environment"]["id"] == quitte
        assert await _events(stack, ENVIRONMENT_MOVED_EVENT) == []


async def test_reposer_le_meme_environnement_ne_change_rien_et_ne_casse_pas(
    blank_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critère 4 — y compris sur un appariement PEUPLÉ : confirmer son état n'est pas bouger.

    Le compte non nul est injecté exprès : si la garde des devices passait avant ce cas,
    un appariement peuplé ne pourrait plus répondre de l'environnement qu'il porte déjà.
    """

    async def _trois(_db: Any, _base_url: str) -> int:
        return 3

    monkeypatch.setattr(environment_link, "db_count_peer_devices", _trois)
    async with open_stack(blank_db, tmp_path) as stack:
        porte = await _cree(stack, "recette")
        await _pose_apparie(stack, "http://stack.test", porte)

        reponse = await _change(stack, "http://stack.test", porte)

        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["environment"]["id"] == porte
        # Aucun event : il ne s'est rien passé, et un journal qui dirait le contraire
        # ferait chercher un déplacement inexistant.
        assert await _events(stack, ENVIRONMENT_MOVED_EVENT) == []


async def test_changer_vers_un_environnement_deja_apparie_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : un environnement ne porte qu'un appariement, et la base le tient."""
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        pris_par_un_autre = await _cree(stack, "production")
        await _pose_apparie(stack, "http://stack.test", quitte)
        await _pose_apparie(stack, "http://autre.test", pris_par_un_autre)

        reponse = await _change(stack, "http://stack.test", pris_par_un_autre)

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "environnement_apparie"
        assert (await _pair(stack, "http://stack.test"))["environment"]["id"] == quitte
        assert (await _pair(stack, "http://autre.test"))["environment"]["id"] == pris_par_un_autre


async def test_deux_appariements_vers_le_meme_environnement_n_en_laissent_passer_qu_un(
    blank_db: str, tmp_path: Path
) -> None:
    """La course que la lecture préalable ne voit pas : c'est LA CONTRAINTE qui tranche.

    Deux appariements se déplacent en même temps vers le même environnement libre. Chacun
    le voit libre, et seule la contrainte d'unicité en base en refuse un — une lecture
    préalable les laisserait tous deux passer, et « à quelle stack appartient ce device »
    n'aurait plus de réponse unique.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        premier = await _cree(stack, "recette")
        second = await _cree(stack, "preprod")
        vise = await _cree(stack, "production")
        await _pose_apparie(stack, "http://une.test", premier)
        await _pose_apparie(stack, "http://deux.test", second)

        reponses = await asyncio.gather(
            _change(stack, "http://une.test", vise),
            _change(stack, "http://deux.test", vise),
        )

        assert sorted(reponse.status_code for reponse in reponses) == [200, 409]
        assert next(r for r in reponses if r.status_code == 409).json()["detail"] == (
            "environnement_apparie"
        )
        porteurs = await stack.pool.fetch(
            "SELECT base_url FROM environment_peer WHERE environment_id = $1::uuid", vise
        )
        assert len(porteurs) == 1


async def test_l_environnement_quitte_redevient_libre(blank_db: str, tmp_path: Path) -> None:
    """Critère 7 : le sélecteur le propose de nouveau, et il redevient supprimable.

    Le sélecteur n'offre que les environnements dont `paired_base_url` est nul : c'est ce
    champ, et lui seul, qui décide de ce qu'il montre.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        pris = await _cree(stack, "preprod")
        await _pose_apparie(stack, "http://stack.test", quitte)
        assert (await _environnement(stack, quitte))["paired_base_url"] == "http://stack.test"

        await _change(stack, "http://stack.test", pris)

        assert (await _environnement(stack, quitte))["paired_base_url"] is None
        assert (await _environnement(stack, pris))["paired_base_url"] == "http://stack.test"
        # Et il se supprime : le refus « cet environnement porte un appariement » tombe
        # avec l'appariement qui l'a quitté.
        assert (await stack.client.delete(f"/api/environments/{quitte}")).status_code == 204


async def test_changer_l_environnement_d_un_appariement_inconnu_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        pris = await _cree(stack, "recette")

        reponse = await _change(stack, "http://inconnue.test", pris)

        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "absent"


async def test_changer_vers_un_environnement_absent_du_referentiel_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Un autre onglet vient de le supprimer : la clé étrangère tient, pas une lecture."""
    async with open_stack(blank_db, tmp_path) as stack:
        quitte = await _cree(stack, "recette")
        disparu = await _cree(stack, "preprod")
        await _pose_apparie(stack, "http://stack.test", quitte)
        assert (await stack.client.delete(f"/api/environments/{disparu}")).status_code == 204

        reponse = await _change(stack, "http://stack.test", disparu)

        assert reponse.status_code == 404
        # « environnement_absent » et non « absent » : le second se lirait « l'appariement
        # a disparu », qui appelle un tout autre geste.
        assert reponse.json()["detail"] == "environnement_absent"
        assert (await _pair(stack, "http://stack.test"))["environment"]["id"] == quitte
