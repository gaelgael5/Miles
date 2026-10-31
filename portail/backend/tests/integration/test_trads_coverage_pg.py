from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from miles.config import Settings
from tests.integration.work_stack import EDITION, Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/trads"
COVERAGE = f"{ROUTE}/coverage"
CULTURES = "/api/workspaces/retrait/cultures"
ROOT = "atelier"
# La culture par défaut du workspace de test. Nommée par une constante et non écrite en
# clair dans les assertions : c'est le WORKSPACE qui la porte, et le test ne doit pas
# dire autre chose que le produit (story 82e60880, critère 6).
DEFAULT = "en-US"
THRESHOLD = Settings.model_fields["trads_low_coverage_percent"].default


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _cultures(forge: Forge, *codes: str) -> None:
    for code in codes:
        added = await forge.client.post(CULTURES, json={"culture": code})
        assert added.status_code == 200, added.text


async def _coverage(forge: Forge, **params: str) -> dict:
    read = await forge.client.get(COVERAGE, params=params, timeout=120)
    assert read.status_code == 200, read.text
    body: dict = read.json()
    return body


def _by_culture(body: dict) -> dict[str, dict]:
    return {row["culture"]: row for row in body["cultures"]}


def _keys(*slugs: str) -> str:
    return "".join(f"{slug}: valeur de {slug}\n" for slug in slugs)


async def test_the_coverage_of_the_installation_sums_every_context(forge: Forge) -> None:
    """Critère 1 : pour chaque culture active, les clés traduites sur le total.

    Deux contextes et non un : c'est la somme qui est mesurée, et un seul contexte ne
    distinguerait pas une somme d'une simple recopie de ses compteurs.
    """
    await _cultures(forge, "fr-FR", "ar-MA")
    await forge.seed(
        {
            f"trads/accueil/{DEFAULT}.yaml": _keys("titre", "adieu", "aide", "retour"),
            "trads/accueil/fr-FR.yaml": _keys("titre", "adieu", "aide", "retour"),
            "trads/accueil/ar-MA.yaml": _keys("titre"),
            f"trads/erreurs/{DEFAULT}.yaml": _keys("refus", "panne"),
        }
    )

    body = await _coverage(forge)
    rows = _by_culture(body)

    assert body["keys"] == 6
    assert (rows[DEFAULT]["translated"], rows[DEFAULT]["missing"]) == (6, 0)
    assert (rows["fr-FR"]["translated"], rows["fr-FR"]["missing"]) == (4, 2)
    assert (rows["ar-MA"]["translated"], rows["ar-MA"]["missing"]) == (1, 5)
    # Critère 2 : le détail par contexte vient avec, dans la même lecture du dépôt.
    assert {c["name"]: c["keys"] for c in body["contexts"]} == {"accueil": 4, "erreurs": 2}


async def test_the_coverage_names_the_branch_it_read_and_the_threshold_it_applied(
    forge: Forge,
) -> None:
    """Critère 11 : deux branches n'ont pas les mêmes clés, l'écran doit dire laquelle."""
    await forge.seed({f"trads/accueil/{DEFAULT}.yaml": _keys("titre")})

    child = await _coverage(forge)
    root = await _coverage(forge, branch=ROOT)

    assert child["branch"] == f"back/retrait/{EDITION}"
    assert child["keys"] == 1
    # La racine n'a pas reçu le semis : la couverture est celle de la branche REGARDÉE,
    # pas celle du workspace.
    assert root["branch"] == f"back/retrait/{ROOT}"
    assert root["keys"] == 0
    assert child["threshold"] == THRESHOLD
    assert child["default"] == DEFAULT


async def test_a_culture_far_under_the_threshold_is_flagged_and_a_complete_one_is_not(
    forge: Forge,
) -> None:
    """Critère 8 : celle-là est visible par des utilisateurs réels, elle se signale."""
    await _cultures(forge, "fr-FR", "ar-MA")
    await forge.seed(
        {
            f"trads/accueil/{DEFAULT}.yaml": _keys("a", "b", "c", "d"),
            "trads/accueil/fr-FR.yaml": _keys("a", "b", "c", "d"),
            "trads/accueil/ar-MA.yaml": _keys("a"),
        }
    )

    rows = _by_culture(await _coverage(forge))

    assert rows["ar-MA"]["low"] is True
    assert rows["fr-FR"]["low"] is False


async def test_the_default_culture_is_never_a_translation_backlog(forge: Forge) -> None:
    """Critère 6 : un manque chez elle est une incohérence du DÉPÔT, pas un retard.

    Le dépôt est semé HORS de Miles, ce qui est la seule façon d'y arriver : la saisie
    exige la valeur de la culture par défaut, et aucune route ne laisse l'omettre.
    """
    await _cultures(forge, "ar-MA")
    await forge.seed(
        {
            f"trads/accueil/{DEFAULT}.yaml": _keys("titre"),
            # `sous-titre` n'existe QUE dans la culture additionnelle : la clé est
            # déclarée, et la culture par défaut n'en porte pas la valeur.
            "trads/accueil/ar-MA.yaml": _keys("titre", "sous-titre"),
        }
    )

    rows = _by_culture(await _coverage(forge))

    assert rows[DEFAULT]["is_default"] is True
    assert rows[DEFAULT]["inconsistent"] is True
    # Jamais « très peu traduite », même à cinquante pour cent : ce n'est pas un travail
    # de traduction, et l'écran ne doit pas l'envoyer à un traducteur.
    assert rows[DEFAULT]["low"] is False
    assert rows["ar-MA"]["inconsistent"] is False


async def test_a_culture_activated_today_starts_from_what_the_repository_already_holds(
    forge: Forge,
) -> None:
    """Critère 7 : retirer une culture garde ses fichiers, et ils comptent au retour."""
    await forge.seed(
        {
            f"trads/accueil/{DEFAULT}.yaml": _keys("titre", "adieu"),
            "trads/accueil/ar-MA.yaml": _keys("titre"),
        }
    )

    before = await _coverage(forge)
    await _cultures(forge, "ar-MA")
    after = await _coverage(forge)

    # Avant son activation, ses fichiers sont comptés comme obsolètes et ne sont pas
    # une couverture : la culture n'est pas du workspace.
    assert "ar-MA" not in _by_culture(before)
    assert before["contexts"][0]["obsolete"] == {"ar-MA": 1}
    # Juste après, sa couverture part de ce qui était là — pas de zéro.
    assert _by_culture(after)["ar-MA"]["translated"] == 1
    assert after["contexts"][0]["obsolete"] == {}


async def test_an_empty_context_enters_the_coverage_without_inflating_it(
    forge: Forge,
) -> None:
    """Critère 9 : compté comme vide, jamais comme couvert à cent pour cent."""
    await forge.seed({f"trads/accueil/{DEFAULT}.yaml": _keys("titre")})
    created = await forge.client.post(
        ROUTE, json={"name": "vide", "label": "Rien dedans"}, timeout=120
    )
    assert created.status_code == 201, created.text

    body = await _coverage(forge)

    assert {c["name"]: c["keys"] for c in body["contexts"]} == {"accueil": 1, "vide": 0}
    assert body["keys"] == 1
    assert _by_culture(body)[DEFAULT]["translated"] == 1


async def test_a_branch_without_any_key_flags_no_culture(forge: Forge) -> None:
    """Une installation qui n'a pas commencé ne voit pas toutes ses langues en alerte."""
    await _cultures(forge, "ar-MA")

    body = await _coverage(forge)
    rows = _by_culture(body)

    assert body["keys"] == 0
    assert [row["low"] for row in body["cultures"]] == [False, False]
    assert rows[DEFAULT]["inconsistent"] is False


async def test_an_unreadable_trads_file_is_named_instead_of_counted_as_missing(
    forge: Forge,
) -> None:
    """Sans ce refus, un fichier cassé rendrait une couverture fausse — donc crédible."""
    await forge.seed({f"trads/accueil/{DEFAULT}.yaml": "- une liste, pas une mappe\n"})

    refused = await forge.client.get(COVERAGE, timeout=120)

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "trads_illisible"
    assert detail["path"] == f"trads/accueil/{DEFAULT}.yaml"
