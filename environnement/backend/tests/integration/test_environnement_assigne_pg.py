from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.keys import generate_keypair
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from tests.integration.environnement_stack import open_stack

pytestmark = pytest.mark.integration

# L'environnement que l'enrôlement nous a assigné : lu chez lui à l'affichage, mémorisé
# ici, et réaffiché daté quand il est injoignable (ticket 2edf1f3c).
#
# Ce module ne CHOISIT pas son environnement et ne doit jamais pouvoir le faire : la
# décision est prise par un humain chez l'enrôlement. Tout ce qui est éprouvé ici porte
# donc sur la LECTURE, sa mémorisation, et la façon de dire ce qu'on affiche.

NOM = "Environnement de recette"


async def _apparie(stack: Any, double: EnrolmentDouble) -> None:
    await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM})
    conclu = await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def _lu(stack: Any) -> dict[str, Any]:
    reponse = await stack.client.get("/api/identity/environment")
    assert reponse.status_code == 200, reponse.text
    charge: dict[str, Any] = reponse.json()
    return charge


async def _memorise(stack: Any) -> Any:
    """Ce que la base garde POUR LE PAIR COURANT. La jointure fait partie de l'assertion.

    Lire la table seule laisserait passer une valeur rangée sous une autre origine, qui est
    exactement ce que ce modèle doit rendre inapplicable : la mémoire est celle du pair qui
    l'a dite, et c'est la jointure qui le dit.
    """
    return await stack.pool.fetchrow(
        "SELECT a.slug, a.label, a.fetched_at FROM assigned_environment a"
        " JOIN enrolment_peer p ON p.base_url = a.base_url WHERE p.id = 'self'"
    )


async def test_l_environnement_assigne_est_lu_chez_le_pair_et_affiche(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : le libellé ET le slug, lus chez l'enrôlement à l'affichage."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)

        vue = await _lu(stack)

        assert vue["fresh"] is True
        assert vue["environment"]["slug"] == "recette"
        assert vue["environment"]["label"] == "Environnement de recette"
        # L'appel est réellement parti : sans cette assertion, une valeur lue d'un cache
        # local passerait pour une lecture fraîche.
        assert double.environment_calls == 1


async def test_la_valeur_lue_est_memorisee_et_relue_au_prochain_affichage(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2 : écrite dans NOTRE base, et c'est elle qui sert de repli ensuite."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        await _lu(stack)

        rangee = await _memorise(stack)

        assert rangee["slug"] == "recette"
        assert rangee["label"] == "Environnement de recette"
        assert rangee["fetched_at"] is not None


async def test_un_pair_injoignable_reaffiche_la_derniere_valeur_connue_datee(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : la valeur mémorisée, SA DATE, et le fait qu'elle n'est pas fraîche.

    Une page qui ne s'affiche que si un autre service répond mentirait sur la nature de la
    panne : l'administrateur croirait son environnement perdu alors qu'un réseau est coupé.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        premiere = await _lu(stack)
        # Le pair ne répond plus du tout : ni refus, ni 200 — une panne.
        double.environment_refusal = (503, "indisponible")

        vue = await _lu(stack)

        assert vue["fresh"] is False
        assert vue["environment"]["slug"] == "recette"
        # La MÊME date que la lecture fraîche : elle dit quand on a appris, pas quand on
        # a réaffiché. Une date qui avancerait à chaque affichage ferait passer un repli
        # pour une lecture de l'instant.
        assert vue["environment"]["fetched_at"] == premiere["environment"]["fetched_at"]


async def test_un_pair_injoignable_sans_valeur_connue_le_dit(blank_db: str, tmp_path: Path) -> None:
    """Critère 4 : ne pas montrer un vide qui se lirait « aucun environnement assigné ».

    Les deux cas rendent `environment: null`, et c'est `fresh` — et lui seul — qui les
    sépare. Les confondre annoncerait « aucun environnement » à un administrateur dont le
    réseau est coupé.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.environment_refusal = (503, "indisponible")

        vue = await _lu(stack)

        assert vue["environment"] is None
        assert vue["fresh"] is False


async def test_une_reponse_fraiche_qui_dit_rien_efface_la_valeur_memorisee(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : une valeur mémorisée ne survit pas à une réponse fraîche qui la contredit."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        await _lu(stack)
        # L'humain, chez l'enrôlement, a détaché cet appariement de son environnement.
        double.environment = None

        vue = await _lu(stack)

        assert vue["environment"] is None
        assert vue["fresh"] is True
        # Effacée EN BASE, et pas seulement dans la réponse : sinon le prochain pair
        # injoignable ressortirait un repli que son autorité a désavoué.
        assert await _memorise(stack) is None


async def test_un_refus_du_pair_n_efface_pas_la_valeur_memorisee(
    blank_db: str, tmp_path: Path
) -> None:
    """Un refus n'est PAS une absence d'environnement, et les confondre détruit du vrai.

    Révocation chez le pair, clés qui ne se correspondent plus, portillon
    d'authentification qui parle avant lui : aucun de ces cas ne dit que nous ne sommes
    rattachés à rien. L'état de l'appariement est l'affaire de l'autre écran.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        await _lu(stack)
        # Le pair a détruit la clé qu'il détenait pour nous : c'est ce que fait une
        # révocation chez lui, et il refuse désormais nos appels signés.
        double.expects_public_key = generate_keypair().public_key

        vue = await _lu(stack)

        assert vue["fresh"] is False
        assert vue["environment"]["slug"] == "recette"
        assert await _memorise(stack) is not None


async def test_un_200_hors_contrat_ne_s_ecrit_pas_dans_notre_base(
    blank_db: str, tmp_path: Path
) -> None:
    """Un 200 ne garantit pas la FORME, et ce qui vient d'un autre service est borné.

    Un intermédiaire, une page d'erreur ou une autre version du pair peuvent rendre 200
    sur autre chose. Le relire quand même écrirait dans notre base ce qu'un inconnu a
    renvoyé — et l'afficherait comme l'autorité sur notre environnement.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.environment_raw = b'{"environnement": "<html>page de connexion</html>"}'

        vue = await _lu(stack)

        assert vue["fresh"] is False
        assert vue["environment"] is None
        assert await _memorise(stack) is None


async def test_un_slug_demesure_est_refuse_avant_d_etre_ecrit(
    blank_db: str, tmp_path: Path
) -> None:
    """La borne du contrat mord sur ce qui ARRIVE, pas seulement sur ce qui part."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.environment = {"slug": "s" * 500, "label": "démesuré"}

        vue = await _lu(stack)

        assert vue["environment"] is None
        assert vue["fresh"] is False
        assert await _memorise(stack) is None


async def test_sans_appariement_il_n_y_a_personne_a_qui_demander(
    blank_db: str, tmp_path: Path
) -> None:
    """404 et non une vue vide : « pas de pair » ne se lit pas « aucun environnement »."""
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.get("/api/identity/environment")

        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "aucun_pair"


async def test_la_route_exige_une_session(blank_db: str, tmp_path: Path) -> None:
    """Fail closed : c'est une route d'administration, pas une route de pair."""
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as visiteur:
        reponse = await visiteur.get("/api/identity/environment")

        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "session_requise"


async def test_le_repli_appartient_au_pair_qui_l_a_dit_et_a_lui_seul(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux règles opposées sur la même mémoire, et les deux sont justes.

    Une stack qui tourne ses clés chez le MÊME enrôlement garde son repli daté, qui reste
    vrai. Un pair DIFFÉRENT n'a jamais rien dit de nous : montrer comme repli ce qu'un
    autre module avait décidé serait un mensonge que la date ne rattraperait pas.

    La mémoire n'est donc pas EFFACÉE quand le pair change — elle CESSE DE S'APPLIQUER,
    parce qu'elle est rangée sous l'origine de celui qui l'a dite (migration 14). La
    nuance se mesure : revenir chez le premier enrôlement retrouve ce que celui-là avait
    dit. C'est vrai, et la date le dit — là où un effacement aurait prétendu qu'on n'avait
    jamais rien su.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        await _lu(stack)

        # Même identité, clés neuves : le repli survit.
        double.expects_public_key = ""
        await _apparie(stack, double)
        assert (await _memorise(stack))["slug"] == "recette"

        # Un autre enrôlement : le repli de l'ancien n'a plus rien à dire de nous.
        autre = await stack.client.put(
            "/api/identity/peer",
            json={
                "base_url": "http://autre-enrolement.test",
                "public_key": generate_keypair().public_key,
            },
        )
        assert autre.status_code == 200, autre.text
        assert await _memorise(stack) is None

        # Et de retour chez le premier, ce qu'il avait dit est de nouveau le nôtre. Sans
        # cette assertion, le modèle « rangé sous l'origine » serait indiscernable d'un
        # effacement, et personne ne verrait la différence avant de la perdre.
        retour = await stack.client.put(
            "/api/identity/peer",
            json={"base_url": PEER_ORIGIN, "public_key": generate_keypair().public_key},
        )
        assert retour.status_code == 200, retour.text
        assert (await _memorise(stack))["slug"] == "recette"
