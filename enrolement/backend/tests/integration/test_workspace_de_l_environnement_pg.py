"""Le workspace dont un environnement héberge le paramétrage (Gael, 01/11/2026).

La seule source des workspaces est la liste que le module de paramétrage CONFIE : cette
campagne monte donc un vrai appariement de paramétrage et un vrai confiage, plutôt que
d'écrire les lignes à la main — c'est le couplage entre les deux qui est éprouvé ici, et
l'écrire à la main le ferait disparaître.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from enrolement.environments.model import (
    ENVIRONMENT_WORKSPACE_CLEARED_EVENT,
    ENVIRONMENT_WORKSPACE_PLACED_EVENT,
)
from tests.integration.demandeur_double import RequesterDouble, confide_body, connexion
from tests.integration.enrolement_stack import (
    EnrolementStack,
    conclut_appariement,
    demande_appariement,
    open_stack,
)

pytestmark = pytest.mark.integration

CREDENTIAL = "pat-de-test-placement-ne-doit-jamais-sortir"


async def _parametrage_qui_expose(stack: EnrolementStack, *workspaces: str) -> RequesterDouble:
    """Un module de paramétrage apparié, qui nous confie une connexion servant `workspaces`."""
    double = RequesterDouble(origin="http://parametrage.test", species="parametrage")
    await demande_appariement(stack, double)
    await conclut_appariement(stack, double)
    charge = confide_body(
        1,
        [
            connexion(
                "forge",
                CREDENTIAL,
                workspaces=[(w, f"https://github.com/yoops/{w}.git") for w in workspaces],
            )
        ],
    )
    confie = await double.confide(stack.anonymous(), charge)
    assert confie.status_code == 200, confie.text
    return double


async def _environnement(stack: EnrolementStack, label: str, slug: str) -> str:
    cree = await stack.client.post("/api/environments", json={"label": label, "slug": slug})
    assert cree.status_code == 201, cree.text
    return str(cree.json()["id"])


async def _place(stack: EnrolementStack, environment_id: str, workspace_id: str | None) -> Any:
    return await stack.client.put(
        f"/api/environments/{environment_id}/workspace", json={"workspace_id": workspace_id}
    )


async def _types(stack: EnrolementStack) -> list[str]:
    rows = await stack.pool.fetch(
        "SELECT type FROM events WHERE type LIKE 'environment.workspace%' ORDER BY written_at"
    )
    return [row["type"] for row in rows]


async def test_un_workspace_expose_se_place_sur_un_environnement_et_se_relit(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams")
        environnement = await _environnement(stack, "Recette nord", "recette-nord")

        place = await _place(stack, environnement, "ams")
        liste = await stack.client.get("/api/environments")

        assert place.status_code == 200, place.text
        assert place.json()["workspace_id"] == "ams"
        assert [e["workspace_id"] for e in liste.json()] == ["ams"]
        assert await _types(stack) == [ENVIRONMENT_WORKSPACE_PLACED_EVENT]


async def test_un_workspace_que_personne_n_expose_est_refuse_en_nommant_ceux_qui_existent(
    blank_db: str, tmp_path: Path
) -> None:
    """Deviner n'est pas une réponse : un agent réessaierait indéfiniment la même valeur."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams", "caisse")
        environnement = await _environnement(stack, "Recette nord", "recette-nord")

        refuse = await _place(stack, environnement, "inexistant")

        assert refuse.status_code == 409, refuse.text
        assert refuse.json()["detail"] == {
            "code": "workspace_non_expose",
            "exposes": ["ams", "caisse"],
        }


async def test_sans_module_de_parametrage_apparie_aucun_workspace_ne_se_place(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        environnement = await _environnement(stack, "Recette nord", "recette-nord")

        refuse = await _place(stack, environnement, "ams")

        assert refuse.status_code == 409, refuse.text
        assert refuse.json()["detail"]["exposes"] == []


async def test_le_workspace_se_retire_et_le_retrait_est_un_fait_distinct(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams")
        environnement = await _environnement(stack, "Recette nord", "recette-nord")
        await _place(stack, environnement, "ams")

        retire = await _place(stack, environnement, None)

        assert retire.status_code == 200, retire.text
        assert retire.json()["workspace_id"] is None
        assert await _types(stack) == [
            ENVIRONMENT_WORKSPACE_PLACED_EVENT,
            ENVIRONMENT_WORKSPACE_CLEARED_EVENT,
        ]


async def test_le_retrait_reste_possible_quand_le_parametrage_a_ete_revoque(
    blank_db: str, tmp_path: Path
) -> None:
    """La révocation emporte la liste exposée : défaire un placement ne doit pas en dépendre."""
    async with open_stack(blank_db, tmp_path) as stack:
        parametrage = await _parametrage_qui_expose(stack, "ams")
        environnement = await _environnement(stack, "Recette nord", "recette-nord")
        await _place(stack, environnement, "ams")
        revoque = await stack.client.delete(
            "/api/pairing/peers", params={"base_url": parametrage.origin}
        )
        assert revoque.status_code in (200, 204), revoque.text

        retire = await _place(stack, environnement, None)
        replace = await _place(stack, environnement, "ams")

        assert retire.status_code == 200, retire.text
        # Replacer, en revanche, n'est plus possible : plus personne ne l'expose.
        assert replace.status_code == 409, replace.text


async def test_deux_environnements_hebergent_le_meme_workspace(
    blank_db: str, tmp_path: Path
) -> None:
    """Recette et production servent le même paramétrage : c'est le cas courant."""
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams")
        recette = await _environnement(stack, "Recette nord", "recette-nord")
        production = await _environnement(stack, "Production", "production")

        premier = await _place(stack, recette, "ams")
        second = await _place(stack, production, "ams")

        assert premier.status_code == 200, premier.text
        assert second.status_code == 200, second.text


async def test_une_saisie_vide_est_refusee_en_nommant_le_champ(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams")
        environnement = await _environnement(stack, "Recette nord", "recette-nord")

        refuse = await _place(stack, environnement, "   ")

        assert refuse.status_code == 422, refuse.text
        assert refuse.json()["detail"] == "workspace_id"


async def test_placer_sur_un_environnement_absent_rend_404(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _parametrage_qui_expose(stack, "ams")

        absent = await _place(stack, str(uuid4()), "ams")

        assert absent.status_code == 404, absent.text
