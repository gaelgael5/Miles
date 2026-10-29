from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.calls import SIGNATURE_HEADER
from miles_socle.signing.keys import generate_keypair

from enrolement.pairing.model import PAIRING_REVOKED_EVENT, PairingRefusedError
from tests.integration.enrolement_stack import EnrolementStack, open_stack
from tests.integration.environnement_double import EnvironmentDouble

pytestmark = pytest.mark.integration


async def _cree(stack: EnrolementStack, slug: str) -> str:
    reponse = await stack.client.post(
        "/api/environments", json={"label": f"Environnement {slug}", "slug": slug}
    )
    assert reponse.status_code == 201, reponse.text
    return str(reponse.json()["id"])


async def _apparie(stack: EnrolementStack, double: EnvironmentDouble, slug: str) -> str:
    """Appariement complet par les ROUTES, désignation comprise. Rend l'environnement.

    Par les routes et non par une écriture directe : ce qu'on révoque ensuite doit être
    un appariement qui a réellement traversé le protocole, clés et code compris. Un
    appariement posé à la main ne prouverait pas que la révocation défait ce que
    l'appariement a fait.
    """
    environment_id = await _cree(stack, slug)
    async with stack.anonymous() as pair:
        assert (await double.knock(pair)).status_code == 202
        designation = await stack.client.put(
            "/api/pairing/requests/environment",
            params={"base_url": double.origin},
            json={"environment_id": environment_id},
        )
        assert designation.status_code == 200, designation.text
        code = await stack.client.get("/api/pairing/code", params={"base_url": double.origin})
        assert code.status_code == 200, code.text
        conclu = await double.confirm(pair, code.json()["code"])
    assert conclu.status_code == 200, conclu.text
    return environment_id


async def _revoque(stack: EnrolementStack, origine: str) -> Any:
    return await stack.client.delete("/api/pairing/peers", params={"base_url": origine})


async def _herite(stack: EnrolementStack, origine: str) -> None:
    """Un appariement SANS environnement : l'état hérité d'avant la désignation."""
    await stack.pool.execute(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, name) VALUES ($1, $2, 'ed25519', now(), now(), 'Hérité')",
        origine,
        generate_keypair().public_key,
    )


async def _environnement(stack: EnrolementStack, environment_id: str) -> dict[str, Any]:
    reponse = await stack.client.get("/api/environments")
    return next(e for e in reponse.json() if e["id"] == environment_id)


async def test_revoquer_detruit_l_appariement_et_sa_cle(blank_db: str, tmp_path: Path) -> None:
    """Critère 8 : clés DÉTRUITES, pas marquées inactives. La ligne entière disparaît."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")

        reponse = await _revoque(stack, double.origin)

        assert reponse.status_code == 204, reponse.text
        assert (await stack.client.get("/api/pairing/peers")).json() == []
        # La clé n'est pas « quelque part avec un drapeau » : il n'y a plus de ligne. Un
        # filtre oublié sur un drapeau ne se voit pas en test ; une ligne absente, si.
        reste = await stack.pool.fetchval(
            "SELECT count(*) FROM environment_peer WHERE base_url = $1", double.origin
        )
        assert reste == 0


async def test_un_appel_signe_apres_revocation_est_refuse(blank_db: str, tmp_path: Path) -> None:
    """Critère 4, premier volet : la stack révoquée n'est plus servie."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")
        async with stack.anonymous() as pair:
            assert (await double.ping(pair)).status_code == 200

            await _revoque(stack, double.origin)
            refus = await double.ping(pair)

        assert refus.status_code == 401


async def test_le_refus_d_une_origine_revoquee_le_dit_au_journal_et_pas_a_l_appelant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4, second volet : le mot change au JOURNAL, jamais dans la réponse.

    Les deux moitiés comptent. Sans le mot, le diagnostic part chercher une clé perdue
    alors qu'un humain a décidé. Avec lui dans la réponse, n'importe qui apprendrait
    qu'une origine a été appariée puis révoquée — l'oracle que tout le protocole refuse.
    """
    revoquee, jamais_appariee = EnvironmentDouble(), EnvironmentDouble(origin="http://autre.test")
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, revoquee, "recette")
        await _revoque(stack, revoquee.origin)

        raisons = []
        for double in (revoquee, jamais_appariee):
            corps = b"{}"
            with pytest.raises(PairingRefusedError) as refus:
                await stack.pairing.resolve_verify_incoming(
                    declared_origin=double.origin,
                    signature=double.headers("/api/peer/ping", corps)[SIGNATURE_HEADER],
                    method="POST",
                    target="/api/peer/ping",
                    body=corps,
                )
            raisons.append(refus.value.reason)

        # Le journal distingue…
        assert raisons == ["origine_revoquee", "origine_inconnue"]

        # …et l'appelant, lui, reçoit exactement la même chose dans les deux cas.
        async with stack.anonymous() as pair:
            reponses = [await double.ping(pair) for double in (revoquee, jamais_appariee)]
        assert [r.status_code for r in reponses] == [401, 401]
        assert reponses[0].json() == reponses[1].json()


async def test_l_environnement_reste_au_referentiel_et_redevient_libre(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12 : révoquer porte sur l'appariement, jamais sur l'environnement."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        environment_id = await _apparie(stack, double, "recette")
        assert (await _environnement(stack, environment_id))["paired_base_url"] == double.origin

        await _revoque(stack, double.origin)

        libere = await _environnement(stack, environment_id)
        assert libere["paired_base_url"] is None
        # Et il est réellement libre, pas seulement affiché comme tel : la suppression
        # était refusée tant qu'il portait un appariement, elle passe maintenant.
        assert (await stack.client.delete(f"/api/environments/{environment_id}")).status_code == 204


async def test_une_origine_revoquee_peut_se_reapparier_et_perd_sa_pierre_tombale(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7 : une révocation ne se défait pas, elle se recommence — code neuf compris."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")
        await _revoque(stack, double.origin)

        # Une demande NEUVE, un secret neuf, un consentement humain neuf : `_apparie`
        # refait tout le protocole. Le nouvel environnement est un autre, parce que le
        # premier a été libéré et pourrait tout aussi bien avoir été repris ailleurs.
        await _apparie(stack, double, "recette-2")

        async with stack.anonymous() as pair:
            assert (await double.ping(pair)).status_code == 200
        # La pierre tombale est partie avec le réappariement : la garder ferait dater une
        # révocation ultérieure de la précédente.
        tombes = await stack.pool.fetchval(
            "SELECT count(*) FROM revoked_pairing WHERE base_url = $1", double.origin
        )
        assert tombes == 0


async def test_revoquer_un_appariement_herite_sans_environnement_est_permis(
    blank_db: str, tmp_path: Path
) -> None:
    """Un appariement d'avant la désignation se révoque comme les autres."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _herite(stack, "http://herite.test")

        reponse = await _revoque(stack, "http://herite.test")

        assert reponse.status_code == 204, reponse.text
        assert (await stack.client.get("/api/pairing/peers")).json() == []


async def test_revoquer_deux_fois_rend_une_disparition_et_non_une_erreur(
    blank_db: str, tmp_path: Path
) -> None:
    """Le second clic porte sur une ligne qui n'existe plus : 404, et la liste le dira."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")
        assert (await _revoque(stack, double.origin)).status_code == 204

        reponse = await _revoque(stack, double.origin)

        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "absent"


async def test_revoquer_le_dernier_appariement_est_permis(blank_db: str, tmp_path: Path) -> None:
    """Critère 11 : un module d'enrôlement sans environnement est son état du premier jour."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double, "recette")

        assert (await _revoque(stack, double.origin)).status_code == 204

        assert (await stack.client.get("/api/pairing/peers")).json() == []
        # Et le module continue de servir : une nouvelle stack peut frapper.
        async with stack.anonymous() as pair:
            neuve = EnvironmentDouble(origin="http://neuve.test")
            assert (await neuve.knock(pair)).status_code == 202


async def test_l_event_de_revocation_porte_l_auteur_l_environnement_et_les_devices(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10 : c'est la trace qu'on cherchera si des devices ne démarrent plus."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        environment_id = await _apparie(stack, double, "recette")

        await _revoque(stack, double.origin)

        ligne = await stack.pool.fetchrow(
            "SELECT properties, author_directory, author_subject FROM events WHERE type = $1",
            PAIRING_REVOKED_EVENT,
        )
        assert ligne is not None
        # `jsonb` revient en CHAÎNE : asyncpg ne décode pas sans codec.
        proprietes = json.loads(ligne["properties"])
        assert proprietes["environment_id"] == environment_id
        assert proprietes["environment_slug"] == "recette"
        assert proprietes["environment_label"] == "Environnement recette"
        # NUL et jamais 0 : le référentiel des devices n'existe pas, et un zéro serait
        # indiscernable dans un an d'un vrai « aucun device n'a été libéré ».
        assert proprietes["devices_released"] is None
        assert ligne["author_directory"] != ""
        assert ligne["author_subject"] != ""


async def test_la_route_de_revocation_exige_une_session(blank_db: str, tmp_path: Path) -> None:
    """Critère 9 : même niveau que l'acceptation d'un appariement, et fail closed."""
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as visiteur:
        reponse = await visiteur.delete(
            "/api/pairing/peers", params={"base_url": "http://environnement.test"}
        )

        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "session_requise"
