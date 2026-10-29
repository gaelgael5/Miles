from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.keys import generate_keypair

from enrolement.pairing.model import (
    ENVIRONMENT_ATTACHED_EVENT,
    ENVIRONMENT_DESIGNATED_EVENT,
)
from tests.integration.enrolement_stack import EnrolementStack, open_stack
from tests.integration.environnement_double import EnvironmentDouble

pytestmark = pytest.mark.integration


async def _cree(stack: EnrolementStack, slug: str) -> str:
    reponse = await stack.client.post(
        "/api/environments", json={"label": f"Environnement {slug}", "slug": slug}
    )
    assert reponse.status_code == 201, reponse.text
    return str(reponse.json()["id"])


async def _designe(stack: EnrolementStack, origine: str, environment_id: str) -> Any:
    return await stack.client.put(
        "/api/pairing/requests/environment",
        params={"base_url": origine},
        json={"environment_id": environment_id},
    )


async def _rattache(stack: EnrolementStack, origine: str, environment_id: str) -> Any:
    return await stack.client.put(
        "/api/pairing/peers/environment",
        params={"base_url": origine},
        json={"environment_id": environment_id},
    )


async def _code(stack: EnrolementStack, origine: str) -> Any:
    return await stack.client.get("/api/pairing/code", params={"base_url": origine})


async def _demande(stack: EnrolementStack, origine: str) -> dict[str, Any]:
    attendues = await stack.client.get("/api/pairing/requests")
    return next(d for d in attendues.json() if d["base_url"] == origine)


async def _pair(stack: EnrolementStack, origine: str) -> dict[str, Any]:
    apparies = await stack.client.get("/api/pairing/peers")
    return next(p for p in apparies.json() if p["base_url"] == origine)


async def _herite(stack: EnrolementStack, origine: str) -> None:
    """Pose un appariement SANS environnement : l'état hérité d'avant ce ticket.

    Écrit au niveau des données parce qu'aucune route ne sait plus le produire — et c'est
    précisément ce que le critère 8 demande de rattraper. Le reconstituer par les routes
    prouverait seulement qu'on sait contourner la garde qu'on vient de poser.
    """
    await stack.pool.execute(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, name, contact_url)"
        " VALUES ($1, $2, 'ed25519', now(), now(), 'Hérité', $1)",
        origine,
        generate_keypair().public_key,
    )


async def test_le_code_n_est_pas_revelable_sans_environnement_designe(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1, et c'est l'interdit central du ticket : révéler le code EST accepter."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)

        reponse = await _code(stack, double.origin)

        assert reponse.status_code == 409
        # Le refus NOMME la cause : un « absent » générique ferait chercher la demande,
        # un 403 ferait chercher un droit, et un bouton grisé muet ferait chercher ailleurs.
        assert reponse.json()["detail"] == "environnement_non_designe"
        assert (await _demande(stack, double.origin))["environment"] is None


async def test_l_appariement_conclu_porte_l_environnement_designe(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2 : ce que l'humain désigne est ce à quoi l'appariement se rattache."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        assert (await _designe(stack, double.origin, environment_id)).status_code == 200

        code = (await _code(stack, double.origin)).json()["code"]
        assert (await double.confirm(pair, code)).status_code == 200

        apparie = await _pair(stack, double.origin)
        # Critère 6 : la liste des appariés porte le libellé ET le slug du référentiel.
        assert apparie["environment"] == {
            "id": environment_id,
            "slug": "recette",
            "label": "Environnement recette",
        }
        # Le nom DÉCLARÉ reste affiché à côté, et ne tient lieu de nom nulle part.
        assert apparie["name"] == double.name


async def test_la_designation_se_change_tant_que_l_appariement_n_est_pas_conclu(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : se verrouiller au premier clic obligerait à refuser pour corriger."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        premier = await _cree(stack, "recette")
        second = await _cree(stack, "preprod")
        await _designe(stack, double.origin, premier)

        assert (await _designe(stack, double.origin, second)).status_code == 200

        assert (await _demande(stack, double.origin))["environment"]["slug"] == "preprod"
        code = (await _code(stack, double.origin)).json()["code"]
        assert (await double.confirm(pair, code)).status_code == 200
        assert (await _pair(stack, double.origin))["environment"]["id"] == second


async def test_un_environnement_deja_apparie_n_est_plus_designable(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : deux stacks pour un même environnement, et « à quelle stack appartient
    ce device » n'a plus de réponse unique."""
    premier = EnvironmentDouble()
    second = EnvironmentDouble(origin="http://autre.test")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await premier.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, premier.origin, environment_id)
        await premier.confirm(pair, (await _code(stack, premier.origin)).json()["code"])
        await second.knock(pair)

        reponse = await _designe(stack, second.origin, environment_id)

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "environnement_apparie"
        assert (await _code(stack, second.origin)).status_code == 409


async def test_la_confirmation_echoue_en_le_disant_sans_ecraser_l_appariement_existant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4, seconde moitié : la course se tranche sans écraser, et le code n'est pas brûlé.

    Deux demandes peuvent viser le même environnement — rien ne le consomme avant la
    conclusion. L'une conclut ; l'autre doit être refusée EN LE DISANT, et sa demande
    doit survivre : un code brûlé sur un refus obligerait l'environnement à refrapper
    pour obtenir un code qu'un humain devrait à nouveau révéler.
    """
    premier = EnvironmentDouble()
    second = EnvironmentDouble(origin="http://autre.test")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await premier.knock(pair)
        await second.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, premier.origin, environment_id)
        await _designe(stack, second.origin, environment_id)
        code_second = (await _code(stack, second.origin)).json()["code"]
        await premier.confirm(pair, (await _code(stack, premier.origin)).json()["code"])

        reponse = await second.confirm(pair, code_second)

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "environnement_indisponible"
        # L'appariement du premier est intact, et la demande du second est toujours là.
        assert (await _pair(stack, premier.origin))["environment"]["id"] == environment_id
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM environment_peer WHERE base_url = $1", second.origin
            )
            == 0
        )
        assert (await _demande(stack, second.origin))["base_url"] == second.origin


async def test_une_demande_refusee_laisse_l_environnement_libre(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7 : une désignation ne CONSOMME pas, seule la conclusion le fait."""
    premier = EnvironmentDouble()
    second = EnvironmentDouble(origin="http://autre.test")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await premier.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, premier.origin, environment_id)

        refus = await stack.client.delete(
            "/api/pairing/requests", params={"base_url": premier.origin}
        )
        assert refus.status_code == 204

        await second.knock(pair)
        assert (await _designe(stack, second.origin, environment_id)).status_code == 200


async def test_une_demande_expiree_laisse_l_environnement_libre(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7, par l'autre voie : l'échéance rend l'environnement sans que personne n'agisse."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path, request_ttl_s=1) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, double.origin, environment_id)
        echeance = await stack.pool.fetchval("SELECT expires_at FROM pairing_request")

        await stack.pool.execute(
            "UPDATE pairing_request SET expires_at = $1", echeance - timedelta(days=1)
        )
        assert (await stack.client.get("/api/pairing/requests")).json() == []

        libre = await stack.client.get("/api/environments")
        assert libre.json()[0]["designated_base_url"] is None
        assert libre.json()[0]["paired_base_url"] is None


async def test_le_referentiel_refuse_de_supprimer_un_environnement_designe(
    blank_db: str, tmp_path: Path
) -> None:
    """Effacer la désignation sous le pied de l'humain ferait cesser son code d'être révélable."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, double.origin, environment_id)

        reponse = await stack.client.delete(f"/api/environments/{environment_id}")

        assert reponse.status_code == 409
        # Pas « environnement_apparie » : refuser la demande ou en désigner un autre n'est
        # pas révoquer, et le message doit désigner le bon geste.
        assert reponse.json()["detail"] == "environnement_designe"
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 1


async def test_un_appariement_herite_se_signale_a_rattacher_puis_se_rattache(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8 : sans toucher aux clés ni refaire l'appariement."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _herite(stack, "http://herite.test")
        avant = await _pair(stack, "http://herite.test")
        assert avant["environment"] is None
        environment_id = await _cree(stack, "recette")

        reponse = await _rattache(stack, "http://herite.test", environment_id)

        assert reponse.status_code == 200, reponse.text
        apres = await _pair(stack, "http://herite.test")
        assert apres["environment"]["id"] == environment_id
        # Les clés n'ont pas bougé : c'est un rattrapage, pas un réappariement.
        assert apres["public_key"] == avant["public_key"]


async def test_un_appariement_rattache_ne_se_deplace_plus(blank_db: str, tmp_path: Path) -> None:
    """Critère 5 et interdit explicite : le déplacer emporterait ses devices sans le dire."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _herite(stack, "http://herite.test")
        premier = await _cree(stack, "recette")
        second = await _cree(stack, "preprod")
        await _rattache(stack, "http://herite.test", premier)

        reponse = await _rattache(stack, "http://herite.test", second)

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "appariement_conclu"
        assert (await _pair(stack, "http://herite.test"))["environment"]["id"] == premier


async def test_deux_rattachements_concurrents_n_en_laissent_passer_qu_un(
    blank_db: str, tmp_path: Path
) -> None:
    """La course que la lecture préalable ne voit pas, et que seule la clause SQL ferme.

    MESURÉ le 28/10/2026 : retirer `AND environment_id IS NULL` de l'écriture ne faisait
    rougir aucun test, parce que la lecture du service refuse avant, dans le cas ordinaire.
    Elle ne suffit pourtant pas : deux onglets qui rattachent en même temps la voient tous
    deux vide, et sans la clause la seconde écriture ÉCRASE la première — un déplacement
    silencieux, exactement ce que le ticket interdit. Aucune contrainte d'unicité ne le
    rattraperait, les deux écritures portant sur la MÊME ligne.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        await _herite(stack, "http://herite.test")
        premier = await _cree(stack, "recette")
        second = await _cree(stack, "preprod")

        reponses = await asyncio.gather(
            _rattache(stack, "http://herite.test", premier),
            _rattache(stack, "http://herite.test", second),
        )

        assert sorted(reponse.status_code for reponse in reponses) == [200, 409]
        gagnant = next(r for r in reponses if r.status_code == 200).json()["environment"]["id"]
        assert (await _pair(stack, "http://herite.test"))["environment"]["id"] == gagnant
        assert next(r for r in reponses if r.status_code == 409).json()["detail"] == (
            "appariement_conclu"
        )


async def test_le_reappariement_conserve_l_environnement_et_ne_le_deplace_pas(
    blank_db: str, tmp_path: Path
) -> None:
    """Une stack qui tourne ses clés réapparie le MÊME environnement, jamais un autre."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, double.origin, environment_id)
        await double.confirm(pair, (await _code(stack, double.origin)).json()["code"])

        # La stack refrappe avec une clé neuve : la demande HÉRITE de l'environnement,
        # sans quoi son code ne serait plus révélable et personne ne saurait pourquoi.
        tourne = EnvironmentDouble(origin=double.origin)
        await tourne.knock(pair)
        assert (await _demande(stack, double.origin))["environment"]["id"] == environment_id

        autre = await _cree(stack, "preprod")
        refus = await _designe(stack, double.origin, autre)
        assert refus.status_code == 409
        assert refus.json()["detail"] == "appariement_conclu"

        await tourne.confirm(pair, (await _code(stack, double.origin)).json()["code"])
        apparie = await _pair(stack, double.origin)
        assert apparie["environment"]["id"] == environment_id
        assert apparie["public_key_fingerprint"] != "", apparie


async def test_designer_un_environnement_absent_du_referentiel_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Un autre onglet vient de le supprimer : la clé étrangère tient, pas une lecture préalable."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        assert (await stack.client.delete(f"/api/environments/{environment_id}")).status_code == 204

        reponse = await _designe(stack, double.origin, environment_id)

        assert reponse.status_code == 404
        # « environnement_absent » et non « absent » : le second se lirait « la demande a
        # disparu », qui appelle un tout autre geste.
        assert reponse.json()["detail"] == "environnement_absent"


async def test_designer_une_demande_qui_n_existe_pas_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        environment_id = await _cree(stack, "recette")

        reponse = await _designe(stack, "http://inconnue.test", environment_id)

        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "absent"


async def test_la_designation_et_le_rattachement_sont_des_events_signes_de_leur_auteur(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9 : qui a décidé, quelle demande, quel environnement."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        environment_id = await _cree(stack, "recette")
        await _designe(stack, double.origin, environment_id)
        await _herite(stack, "http://herite.test")
        autre = await _cree(stack, "preprod")
        await _rattache(stack, "http://herite.test", autre)

        lignes = await stack.pool.fetch(
            "SELECT type, properties, author_directory, author_subject FROM events"
            " WHERE type = ANY($1::text[]) ORDER BY type",
            [ENVIRONMENT_ATTACHED_EVENT, ENVIRONMENT_DESIGNATED_EVENT],
        )

        assert [ligne["type"] for ligne in lignes] == [
            ENVIRONMENT_ATTACHED_EVENT,
            ENVIRONMENT_DESIGNATED_EVENT,
        ]
        for ligne in lignes:
            # `jsonb` revient en CHAÎNE : asyncpg ne décode pas sans codec, et comparer
            # des clefs sur la chaîne comparerait ses caractères (mesuré le 28/10/2026).
            proprietes = json.loads(ligne["properties"])
            # Le slug ET le libellé en plus de l'identifiant : relire le journal dans un an
            # se fait sous le nom qu'on employait alors, et les deux sont renommables.
            assert set(proprietes) >= {
                "environment_id",
                "environment_slug",
                "environment_label",
            }
            # L'identité (annuaire, sub) et jamais la personne : une liaison tardive
            # réunifie l'historique sans réécrire le journal.
            assert ligne["author_directory"] != ""
            assert ligne["author_subject"] != ""


async def test_les_routes_de_designation_exigent_une_session(blank_db: str, tmp_path: Path) -> None:
    """Critère 10 : même niveau que l'acceptation d'un appariement, et fail closed."""
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as visiteur:
        for chemin in ("/api/pairing/requests/environment", "/api/pairing/peers/environment"):
            reponse = await visiteur.put(
                chemin,
                params={"base_url": "http://environnement.test"},
                json={"environment_id": "00000000-0000-0000-0000-000000000000"},
            )

            assert reponse.status_code == 401, chemin
            assert reponse.json()["detail"] == "session_requise", chemin


async def test_le_nom_declare_ne_cree_aucun_environnement(blank_db: str, tmp_path: Path) -> None:
    """Interdit explicite : ce texte vient d'un inconnu, il ne nomme pas le référentiel."""
    double = EnvironmentDouble(name="Production")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)

        assert (await stack.client.get("/api/environments")).json() == []
        assert (await _demande(stack, double.origin))["name"] == "Production"
        assert (await _demande(stack, double.origin))["environment"] is None
