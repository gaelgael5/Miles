from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.integration.work_stack import EDITION, Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/trads"
CULTURES = "/api/workspaces/retrait/cultures"


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _add(
    forge: Forge, name: str = "accueil", label: str = "Écrans d'accueil"
) -> httpx.Response:
    return await forge.client.post(ROUTE, json={"name": name, "label": label}, timeout=120)


async def _paths(forge: Forge) -> list[str]:
    """Le contenu réel de la branche, lu à la forge : le dépôt fait foi.

    Publie d'abord : l'administrateur a la main sur la branche, et ses commits restent
    locaux jusque-là (story 9def0adc). Lire la forge sans publier mesurerait l'état
    d'avant le geste.
    """
    if forge.held:
        await forge.publish()
    listed = await forge.api.get(
        f"/api/v1/repos/miles/{forge.name}/git/trees/{forge.edited}",
        params={"recursive": "true"},
    )
    assert listed.status_code == 200, listed.text
    return [e["path"] for e in listed.json()["tree"]]


async def _seed(forge: Forge, files: dict[str, str]) -> None:
    """Pose des fichiers de traduction dans la branche enfant, hors de Miles.

    Hors de Miles exprès : les clés arrivent par l'écran de saisie, qui est un autre
    ticket. Ce qui se mesure ici, c'est que la liste et la suppression lisent le DÉPÔT.

    Publie ce qui est en attente avant de semer : sans cela, le semis et les commits
    locaux partiraient du même parent et la publication suivante serait refusée.
    """
    if forge.held:
        await forge.publish()
    for path, content in files.items():
        written = await forge.api.post(
            f"/api/v1/repos/miles/{forge.name}/contents/{path}",
            json={
                "content": base64.b64encode(content.encode()).decode(),
                "branch": forge.edited,
                "message": f"semis {path}",
            },
        )
        assert written.status_code == 201, written.text


async def _cultures(forge: Forge, *codes: str) -> None:
    for code in codes:
        added = await forge.client.post(CULTURES, json={"culture": code})
        assert added.status_code == 200, added.text


# --- Critères 1 à 4 : créer, nommer, figer ---


async def test_creating_a_context_makes_its_directory_in_the_branch(forge: Forge) -> None:
    created = await _add(forge)

    assert created.status_code == 201, created.text
    assert created.json() == {
        "name": "accueil",
        "label": "Écrans d'accueil",
        "keys": 0,
        "translated": {},
    }
    assert "trads/accueil/contexte.yaml" in await _paths(forge)
    listed = (await forge.client.get(ROUTE, timeout=120)).json()
    assert [(c["name"], c["label"]) for c in listed] == [("accueil", "Écrans d'accueil")]


@pytest.mark.parametrize(
    "hostile", ["../evasion", "a/b", "..", ".", "Accueil", "mes écrans", "accueil ", ""]
)
async def test_invalid_technical_name_is_refused_before_touching_the_repository(
    forge: Forge, hostile: str
) -> None:
    """C'est un nom de répertoire : il ne doit jamais pouvoir sortir de `trads/`."""
    refused = await _add(forge, hostile)

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"field": "name", "reason": "forme"}
    assert not [p for p in await _paths(forge) if p.startswith("trads/") and p != "trads"]


async def test_technical_name_already_taken_names_the_existing_context(forge: Forge) -> None:
    await _add(forge)

    refused = await _add(forge, "accueil", "Un autre libellé")

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "contexte_pris", "label": "Écrans d'accueil"}


async def test_the_label_changes_and_the_technical_name_has_no_route_to_change(
    forge: Forge,
) -> None:
    await _add(forge)

    renamed = await forge.client.put(
        f"{ROUTE}/accueil", json={"label": "Accueil du terminal"}, timeout=120
    )

    assert renamed.status_code == 200, renamed.text
    listed = (await forge.client.get(ROUTE, timeout=120)).json()
    assert listed[0]["label"] == "Accueil du terminal"
    assert listed[0]["name"] == "accueil"
    # Le nom technique entre dans le chemin et dans tout ce qui référencera ses clés :
    # aucune route ne le change, et le corps de renommage n'accepte que le libellé.
    assert (
        await forge.client.put(f"{ROUTE}/accueil", json={"name": "autre", "label": "x"})
    ).status_code == 422


@pytest.mark.parametrize("hostile", ["", "   ", "sur\ndeux lignes"])
async def test_invalid_label_is_refused(forge: Forge, hostile: str) -> None:
    refused = await _add(forge, "accueil", hostile)

    assert refused.status_code == 422
    assert refused.json()["detail"]["field"] == "label"


async def test_relabelling_an_unknown_context_is_a_named_refusal(forge: Forge) -> None:
    answered = await forge.client.put(f"{ROUTE}/absent", json={"label": "x"}, timeout=120)

    assert (answered.status_code, answered.json()["detail"]) == (409, "contexte_inconnu")


# --- Critères 7, 8, 9 : la liste, et le dépôt qui fait foi ---


async def test_the_list_shows_keys_and_coverage_per_workspace_culture(forge: Forge) -> None:
    await _cultures(forge, "fr-FR", "ar-MA")
    await _add(forge)
    await _seed(
        forge,
        {
            "trads/accueil/en-US.yaml": "titre: Hello\nadieu: Bye\n",
            "trads/accueil/fr-FR.yaml": "titre: Bonjour\nadieu: Au revoir\n",
            "trads/accueil/ar-MA.yaml": "titre: مرحبا\n",
        },
    )

    listed = (await forge.client.get(ROUTE, timeout=120)).json()

    assert listed[0]["keys"] == 2
    # en-US est la culture par défaut du workspace de test, et vient en premier.
    assert listed[0]["translated"] == {"en-US": 2, "fr-FR": 2, "ar-MA": 1}


async def test_an_empty_context_is_zero_on_zero_rather_than_fully_covered(forge: Forge) -> None:
    """Zéro clé traduite sur zéro clé n'est pas une bonne nouvelle (critère 8)."""
    await _add(forge, "vide", "Encore vide")

    listed = (await forge.client.get(ROUTE, timeout=120)).json()

    assert (listed[0]["keys"], listed[0]["translated"]) == (0, {"en-US": 0})


async def test_a_directory_present_in_git_without_a_declared_context_is_listed(
    forge: Forge,
) -> None:
    """Le dépôt fait foi, pas un enregistrement parallèle (critère 9)."""
    await _seed(forge, {"trads/venu-dailleurs/en-US.yaml": "titre: Hello\n"})

    listed = (await forge.client.get(ROUTE, timeout=120)).json()

    # Sans fichier de métadonnées, le nom technique fait office de libellé.
    assert listed == [
        {
            "name": "venu-dailleurs",
            "label": "venu-dailleurs",
            "keys": 1,
            "translated": {"en-US": 1},
        }
    ]


async def test_contexts_are_listed_in_a_stable_order(forge: Forge) -> None:
    for name in ("zone", "accueil", "erreurs"):
        assert (await _add(forge, name, f"Libellé {name}")).status_code == 201

    listed = (await forge.client.get(ROUTE, timeout=120)).json()

    assert [c["name"] for c in listed] == ["accueil", "erreurs", "zone"]


async def test_an_unreadable_translation_file_names_the_file(forge: Forge) -> None:
    await _seed(forge, {"trads/accueil/en-US.yaml": "titre: [non fermé\n"})

    answered = await forge.client.get(ROUTE, timeout=120)

    assert answered.status_code == 422
    assert answered.json()["detail"] == {
        "code": "trads_illisible",
        "path": "trads/accueil/en-US.yaml",
    }


# --- Critères 5 et 6 : supprimer ---


async def test_deleting_an_empty_context_removes_its_directory(forge: Forge) -> None:
    await _add(forge, "vide", "Encore vide")

    removed = await forge.client.delete(f"{ROUTE}/vide", timeout=120)

    assert removed.status_code == 200, removed.text
    assert removed.json() == {"keys": 0, "values": 0}
    assert "trads/vide/contexte.yaml" not in await _paths(forge)
    assert (await forge.client.get(ROUTE, timeout=120)).json() == []


async def test_the_removal_preview_announces_keys_and_values_across_cultures(
    forge: Forge,
) -> None:
    """Les deux nombres : dix clés en cinq langues font disparaître cinquante valeurs."""
    await _cultures(forge, "fr-FR")
    await _add(forge)
    await _seed(
        forge,
        {
            "trads/accueil/en-US.yaml": "titre: Hello\nadieu: Bye\n",
            "trads/accueil/fr-FR.yaml": "titre: Bonjour\n",
        },
    )

    preview = await forge.client.get(f"{ROUTE}/accueil/removal", timeout=120)

    assert preview.json() == {"keys": 2, "values": 3}


async def test_deleting_a_populated_context_takes_every_culture_file_with_it(
    forge: Forge,
) -> None:
    await _cultures(forge, "fr-FR")
    await _add(forge)
    await _seed(
        forge,
        {
            "trads/accueil/en-US.yaml": "titre: Hello\nadieu: Bye\n",
            "trads/accueil/fr-FR.yaml": "titre: Bonjour\n",
        },
    )

    removed = await forge.client.delete(f"{ROUTE}/accueil", timeout=120)

    assert removed.json() == {"keys": 2, "values": 3}
    assert [p for p in await _paths(forge) if p.startswith("trads/accueil")] == []


async def test_deleting_one_context_leaves_the_others_untouched(forge: Forge) -> None:
    await _add(forge, "accueil", "Accueil")
    await _add(forge, "erreurs", "Erreurs")
    await _seed(forge, {"trads/erreurs/en-US.yaml": "refus: Refusé\n"})

    assert (await forge.client.delete(f"{ROUTE}/accueil", timeout=120)).status_code == 200

    listed = (await forge.client.get(ROUTE, timeout=120)).json()
    assert [c["name"] for c in listed] == ["erreurs"]
    assert listed[0]["keys"] == 1


async def test_deleting_an_unknown_context_is_a_named_refusal(forge: Forge) -> None:
    answered = await forge.client.delete(f"{ROUTE}/absent", timeout=120)

    assert (answered.status_code, answered.json()["detail"]) == (409, "contexte_inconnu")


@pytest.mark.parametrize("hostile", ["..", "a%2Fb"])
async def test_deleting_through_a_hostile_name_is_refused(forge: Forge, hostile: str) -> None:
    answered = await forge.client.delete(f"{ROUTE}/{hostile}", timeout=120)

    # Refus, jamais une suppression hors de `trads/` : 404 si la route ne correspond pas,
    # 422 si le nom atteint la garde de forme.
    assert answered.status_code in (404, 422)


# --- La branche, les droits, le journal ---


async def test_contexts_are_those_of_the_branch_being_looked_at(forge: Forge) -> None:
    """Deux branches peuvent ne pas avoir les mêmes contextes."""
    await _add(forge)

    on_root = await forge.client.get(ROUTE, params={"branch": "atelier"}, timeout=120)

    assert on_root.json() == []
    assert len((await forge.client.get(ROUTE, timeout=120)).json()) == 1


async def test_the_root_branch_refuses_to_be_written(forge: Forge) -> None:
    refused = await forge.client.post(
        ROUTE, json={"name": "accueil", "label": "Accueil"}, params={"branch": "atelier"}
    )

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "branche_racine_lecture_seule",
    )


async def test_contexts_are_closed_without_a_session(forge: Forge) -> None:
    async with forge.portal.anonymous() as anonymous:
        assert (await anonymous.get(ROUTE)).status_code == 401
        assert (await anonymous.post(ROUTE, json={"name": "x", "label": "x"})).status_code == 401
        assert (await anonymous.put(f"{ROUTE}/x", json={"label": "y"})).status_code == 401
        assert (await anonymous.delete(f"{ROUTE}/x")).status_code == 401


async def test_each_gesture_is_journaled_with_the_context_and_the_branch(forge: Forge) -> None:
    await _add(forge)
    await forge.client.put(f"{ROUTE}/accueil", json={"label": "Accueil"}, timeout=120)
    await forge.client.delete(f"{ROUTE}/accueil", timeout=120)

    rows = await forge.portal.pool.fetch(
        "SELECT type, properties FROM events WHERE type LIKE 'trads_context.%' ORDER BY written_at"
    )
    journaled = [(r["type"], _properties(r["properties"])) for r in rows]

    assert [t for t, _ in journaled] == [
        "trads_context.created",
        "trads_context.relabelled",
        "trads_context.deleted",
    ]
    assert all(p["context"] == "accueil" for _, p in journaled)
    assert all(p["branch"] == f"back/retrait/{EDITION}" for _, p in journaled)
    assert journaled[2][1]["keys"] == 0


def _properties(raw: object) -> dict[str, object]:
    # asyncpg rend une colonne `jsonb` en CHAÎNE, pas en dictionnaire (LESSONS.md).
    return json.loads(raw) if isinstance(raw, str) else dict(raw)  # type: ignore[arg-type]
