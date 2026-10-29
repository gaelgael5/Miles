from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from miles_socle.signing.keys import generate_keypair

from enrolement.environments.model import (
    ENVIRONMENT_CREATED_EVENT,
    ENVIRONMENT_DELETED_EVENT,
    ENVIRONMENT_RENAMED_EVENT,
)
from tests.integration.enrolement_stack import EnrolementStack, open_stack

pytestmark = pytest.mark.integration

RECETTE = {"label": "Recette nord", "slug": "recette-nord"}


async def _cree(stack: EnrolementStack, label: str, slug: str) -> dict[str, object]:
    reponse = await stack.client.post("/api/environments", json={"label": label, "slug": slug})
    assert reponse.status_code == 201, reponse.text
    corps: dict[str, object] = reponse.json()
    return corps


async def _apparie_a_la_main(stack: EnrolementStack, environment_id: str, base_url: str) -> None:
    """Pose l'état que le geste de désignation produira (ticket bf2115cd), au niveau des données.

    Ce ticket crée la colonne sans la remplir : sans ce montage, la garde de suppression
    ne pourrait pas être éprouvée, et un garde-fou jamais vu rouge ne prouve rien.
    """
    await stack.pool.execute(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, environment_id, contact_url)"
        " VALUES ($1, $2, 'ed25519', now(), now(), $3, $1)",
        base_url,
        generate_keypair().public_key,
        environment_id,
    )


async def test_un_environnement_declare_apparait_dans_la_liste_avec_son_slug(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        cree = await _cree(stack, RECETTE["label"], RECETTE["slug"])

        liste = await stack.client.get("/api/environments")

        assert liste.status_code == 200, liste.text
        assert [(e["label"], e["slug"]) for e in liste.json()] == [
            (RECETTE["label"], RECETTE["slug"])
        ]
        # Pas encore apparié, et ce n'est pas une anomalie : c'est l'état du premier jour.
        assert liste.json()[0]["paired_base_url"] is None
        assert cree["id"] == liste.json()[0]["id"]
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", ENVIRONMENT_CREATED_EVENT
            )
            == 1
        )


@pytest.mark.parametrize(
    ("label", "slug", "champ"),
    [
        ("", "recette-nord", "label"),
        ("   ", "recette-nord", "label"),
        ("A" * 81, "recette-nord", "label"),
        ("Tabulation\tinterdite", "recette-nord", "label"),
        ("Recette nord", "", "slug"),
        ("Recette nord", "Recette-Nord", "slug"),
        ("Recette nord", "recette nord", "slug"),
        ("Recette nord", "recette--nord", "slug"),
        ("Recette nord", "-recette", "slug"),
        ("Recette nord", "recette-", "slug"),
        ("Recette nord", "recette_nord", "slug"),
        ("Recette nord", "récette", "slug"),
        ("Recette nord", "a" * 49, "slug"),
    ],
)
async def test_une_saisie_inutilisable_est_refusee_en_nommant_le_champ(
    blank_db: str, tmp_path: Path, label: str, slug: str, champ: str
) -> None:
    """Nommer le champ n'est pas un confort : « corps invalide » fait relire les deux.

    Le libellé de 81 caractères est le cas qui a mordu le 28/10/2026 sur le nom déclaré
    d'un appariement — la borne de schéma parlait avant la règle, et l'écran ne savait
    plus quoi montrer.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.post("/api/environments", json={"label": label, "slug": slug})

        assert reponse.status_code == 422, reponse.text
        assert reponse.json()["detail"] == champ
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 0


async def test_deux_environnements_ne_partagent_pas_un_slug(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _cree(stack, "Recette nord", "recette-nord")

        # Libellé DIFFÉRENT, slug identique : c'est le cas que la casse et les accents
        # produisent sans qu'on y pense, et le refus doit le dire.
        reponse = await stack.client.post(
            "/api/environments", json={"label": "Recette Nord", "slug": "recette-nord"}
        )

        assert reponse.status_code == 409, reponse.text
        assert reponse.json()["detail"] == "slug_pris"
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 1


async def test_deux_creations_concurrentes_du_meme_slug_n_en_laissent_passer_qu_une(
    blank_db: str, tmp_path: Path
) -> None:
    """L'unicité est tenue par la BASE, pas par une lecture préalable.

    Entre un `SELECT` et un `INSERT`, deux appels concurrents passent tous les deux. Ce
    test est le seul endroit où cette différence se voit — et le refus doit rester un 409
    propre, jamais une erreur serveur.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        corps = {"label": "Recette nord", "slug": "recette-nord"}
        reponses = await asyncio.gather(
            stack.client.post("/api/environments", json=corps),
            stack.client.post("/api/environments", json=corps),
            stack.client.post("/api/environments", json=corps),
        )

        codes = sorted(reponse.status_code for reponse in reponses)
        assert codes == [201, 409, 409], [r.text for r in reponses]
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 1


async def test_le_slug_et_le_libelle_se_renomment_et_l_event_dit_ce_qu_il_y_avait_avant(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        cree = await _cree(stack, "Recetta nord", "recetta-nord")

        reponse = await stack.client.put(
            f"/api/environments/{cree['id']}",
            json={"label": "Recette nord", "slug": "recette-nord"},
        )

        assert reponse.status_code == 200, reponse.text
        assert (reponse.json()["label"], reponse.json()["slug"]) == ("Recette nord", "recette-nord")
        # L'identifiant ne bouge pas : c'est pour cela que l'appariement le référence.
        assert reponse.json()["id"] == cree["id"]
        proprietes = await stack.pool.fetchval(
            "SELECT properties FROM events WHERE type = $1", ENVIRONMENT_RENAMED_EVENT
        )
        assert '"previous_slug": "recetta-nord"' in proprietes
        assert '"previous_label": "Recetta nord"' in proprietes


async def test_un_renommage_vers_un_slug_pris_est_refuse_et_ne_change_rien(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _cree(stack, "Production", "production")
        recette = await _cree(stack, "Recette nord", "recette-nord")

        reponse = await stack.client.put(
            f"/api/environments/{recette['id']}",
            json={"label": "Recette nord", "slug": "production"},
        )

        assert reponse.status_code == 409, reponse.text
        assert reponse.json()["detail"] == "slug_pris"
        inchange = await stack.pool.fetchval(
            "SELECT slug FROM environment WHERE id = $1::uuid", recette["id"]
        )
        assert inchange == "recette-nord"


async def test_renommer_un_environnement_absent_rend_404(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.put(
            f"/api/environments/{uuid4()}", json={"label": "Ailleurs", "slug": "ailleurs"}
        )

        assert reponse.status_code == 404, reponse.text
        assert reponse.json()["detail"] == "absent"


async def test_un_environnement_libre_se_supprime(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        cree = await _cree(stack, RECETTE["label"], RECETTE["slug"])

        reponse = await stack.client.delete(f"/api/environments/{cree['id']}")

        assert reponse.status_code == 204, reponse.text
        assert (await stack.client.get("/api/environments")).json() == []
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", ENVIRONMENT_DELETED_EVENT
            )
            == 1
        )


async def test_un_environnement_apparie_ne_se_supprime_pas(blank_db: str, tmp_path: Path) -> None:
    """Supprimer emporterait l'appariement, et les devices avec lui. On révoque d'abord."""
    async with open_stack(blank_db, tmp_path) as stack:
        cree = await _cree(stack, RECETTE["label"], RECETTE["slug"])
        await _apparie_a_la_main(stack, str(cree["id"]), "https://recette.exemple.org")

        reponse = await stack.client.delete(f"/api/environments/{cree['id']}")

        assert reponse.status_code == 409, reponse.text
        # Refus NOMMÉ : « révoquez d'abord » et « il reste des devices » appelleront deux
        # gestes différents, et un message unique les confondrait.
        assert reponse.json()["detail"] == "environnement_apparie"
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 1
        liste = await stack.client.get("/api/environments")
        assert liste.json()[0]["paired_base_url"] == "https://recette.exemple.org"


async def test_un_environnement_ne_porte_jamais_deux_appariements(
    blank_db: str, tmp_path: Path
) -> None:
    """Contrainte du MODÈLE, pas de l'écran : deux stacks pour un environnement, et « à
    quelle stack appartient ce device » n'a plus de réponse unique.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        cree = await _cree(stack, RECETTE["label"], RECETTE["slug"])
        await _apparie_a_la_main(stack, str(cree["id"]), "https://recette.exemple.org")

        with pytest.raises(Exception, match="environment_peer_environment_unique"):
            await _apparie_a_la_main(stack, str(cree["id"]), "https://autre.exemple.org")


async def test_les_appariements_sans_environnement_restent_possibles(
    blank_db: str, tmp_path: Path
) -> None:
    """La colonne est NULLABLE, et il le faut : des appariements existent déjà sans elle.

    Les signaler « à rattacher » est le ticket voisin ; ce qui compte ici est qu'ils ne
    se gênent pas entre eux — PostgreSQL admet plusieurs NULL sous un UNIQUE.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        for origine in ("https://une.exemple.org", "https://autre.exemple.org"):
            await stack.pool.execute(
                "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
                " updated_at, contact_url)"
                " VALUES ($1, $2, 'ed25519', now(), now(), $1)",
                origine,
                generate_keypair().public_key,
            )

        assert await stack.pool.fetchval("SELECT count(*) FROM environment_peer") == 2


async def test_aucune_route_du_referentiel_n_est_atteignable_sans_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Fail closed : le référentiel décide où des devices pourront atterrir."""
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as visiteur:
        appels = (
            visiteur.get("/api/environments"),
            visiteur.post("/api/environments", json=RECETTE),
            visiteur.put(f"/api/environments/{uuid4()}", json=RECETTE),
            visiteur.delete(f"/api/environments/{uuid4()}"),
        )
        for reponse in await asyncio.gather(*appels):
            assert reponse.status_code == 401, reponse.text
        assert await stack.pool.fetchval("SELECT count(*) FROM environment") == 0
