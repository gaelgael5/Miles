from __future__ import annotations

import yaml

from miles.workshop.trads import Context, file_contexts
from miles.workshop.trads_coverage import Coverage, CultureCoverage, rolled_up

# `en-US` par défaut ET `fr-FR` à cent pour cent dans le même jeu d'essai : c'est ce qui
# rend le test discriminant sur le critère 6. Un jeu où la culture par défaut serait la
# seule complète laisserait passer un code qui traite `en-US` comme obligatoire.
CONTEXTS = [
    Context("accueil", "Accueil", 10, {"en-US": 10, "fr-FR": 10, "ar-MA": 2}, {}),
    Context("erreurs", "Erreurs", 30, {"en-US": 30, "fr-FR": 30, "ar-MA": 1}, {}),
]
CULTURES = ("en-US", "fr-FR", "ar-MA")


def _rolled(
    contexts: list[Context],
    default: str = "en-US",
    cultures: tuple[str, ...] = CULTURES,
    threshold: int = 50,
) -> tuple[Coverage, dict[str, CultureCoverage]]:
    """La couverture et ses lignes indexées par culture : les tests lisent par code."""
    coverage = rolled_up(
        contexts, default, cultures, branch="back/retrait/edition", threshold=threshold
    )
    return coverage, {row.culture: row for row in coverage.cultures}


def test_the_installation_total_is_the_sum_of_the_contexts() -> None:
    coverage, rows = _rolled(CONTEXTS)

    assert coverage.keys == 40
    assert (rows["ar-MA"].translated, rows["ar-MA"].missing) == (3, 37)
    assert (rows["fr-FR"].translated, rows["fr-FR"].missing) == (40, 0)


def test_the_branch_read_and_the_threshold_come_back_with_the_counts() -> None:
    """L'écran annonce le signalement AVEC sa borne, et dit quelle branche il montre."""
    coverage = _rolled(CONTEXTS, threshold=70)[0]

    assert coverage.branch == "back/retrait/edition"
    assert coverage.threshold == 70
    assert coverage.default == "en-US"


def test_a_culture_under_the_threshold_is_flagged_and_the_others_are_not() -> None:
    rows = _rolled(CONTEXTS, threshold=50)[1]

    assert rows["ar-MA"].low is True
    assert rows["fr-FR"].low is False


def test_the_threshold_is_a_floor_not_a_ceiling() -> None:
    """Exactement au seuil, la culture n'est PAS signalée : c'est en DESSOUS qu'on alerte."""
    exact = [Context("accueil", "Accueil", 10, {"en-US": 10, "fr-FR": 5}, {})]

    at = _rolled(exact, cultures=("en-US", "fr-FR"), threshold=50)[1]
    just_under = _rolled(exact, cultures=("en-US", "fr-FR"), threshold=51)[1]

    assert at["fr-FR"].low is False
    assert just_under["fr-FR"].low is True


def test_the_default_culture_of_the_workspace_is_never_presented_as_work_to_do() -> None:
    """Critère 6 : chez elle, un manque est une incohérence du DÉPÔT, pas un retard."""
    broken = [Context("accueil", "Accueil", 10, {"fr-FR": 3, "en-US": 10}, {})]

    rows = _rolled(broken, default="fr-FR", cultures=("fr-FR", "en-US"))[1]

    assert rows["fr-FR"].is_default is True
    # Très en dessous du seuil, et pourtant pas « très peu traduite » : la culture par
    # défaut ne figure jamais dans la liste de travail d'un traducteur.
    assert rows["fr-FR"].low is False
    assert rows["fr-FR"].inconsistent is True


def test_en_us_is_only_the_default_culture_of_a_new_workspace_and_carries_no_rule() -> None:
    """La règle du 30/10/2026 : l'obligation suit le WORKSPACE, pas le code `en-US`."""
    rows = _rolled(CONTEXTS, default="fr-FR")[1]

    assert rows["fr-FR"].is_default is True
    assert rows["en-US"].is_default is False
    # `en-US` complète ici, donc rien à signaler — mais c'est `fr-FR` qui porte
    # désormais l'incohérence éventuelle, et elle est complète aussi.
    assert rows["fr-FR"].inconsistent is False
    assert rows["en-US"].inconsistent is False


def test_a_complete_default_culture_reports_no_inconsistency() -> None:
    rows = _rolled(CONTEXTS)[1]

    assert rows["en-US"].inconsistent is False


def test_a_branch_without_any_key_flags_nothing() -> None:
    """Zéro sur zéro n'est pas une mauvaise nouvelle : une installation qui n'a pas
    commencé ne doit pas voir toutes ses langues en alerte (même esprit que le critère 9
    pour un contexte vide)."""
    rows = _rolled([], threshold=90)[1]

    assert rows["ar-MA"].low is False
    assert rows["ar-MA"].missing == 0
    assert rows["en-US"].inconsistent is False


def test_an_empty_context_counts_as_empty_and_not_as_covered() -> None:
    """Critère 9 : il entre dans la couverture avec zéro clé, il ne la gonfle pas."""
    with_empty = [*CONTEXTS, Context("vide", "Vide", 0, dict.fromkeys(CULTURES, 0), {})]

    coverage = _rolled(with_empty)[0]

    assert coverage.keys == 40
    assert [c.name for c in coverage.contexts] == ["accueil", "erreurs", "vide"]


async def test_a_culture_added_today_starts_from_what_the_repository_already_holds() -> None:
    """Critère 7 : ses fichiers sont restés, et ils comptent dès sa réactivation."""
    files = {
        "trads/accueil/en-US.yaml": "titre: Hello\nadieu: Bye\n",
        # Désactivée puis réactivée : le retrait d'une culture garde ses fichiers, exprès.
        "trads/accueil/ar-MA.yaml": "titre: مرحبا\n",
    }
    paths = [*files, "trads/accueil/contexte.yaml"]

    async def read(path: str) -> str | None:
        return files.get(path)

    contexts = await file_contexts(read, paths, ["en-US", "ar-MA"])
    rows = _rolled(contexts, cultures=("en-US", "ar-MA"))[1]

    assert rows["ar-MA"].translated == 1
    assert rows["ar-MA"].missing == 1


async def test_each_culture_file_is_read_once_on_a_large_branch() -> None:
    """Critère 10 : les compteurs sont justes, et le coût ne double pas.

    Le détail par culture et le total venaient de deux parcours, donc de deux lectures et
    de deux analyses YAML du même fichier. La mesure porte sur le NOMBRE d'appels à
    `read`, parce qu'un compteur juste ne dit rien du travail fourni pour l'obtenir.
    """
    cultures = [f"xx-{n:02d}" for n in range(10)]
    keys = [f"cle-{n:04d}" for n in range(2000)]
    files = {
        f"trads/accueil/{culture}.yaml": yaml.safe_dump(
            # La dernière culture n'a que la moitié des clés : sans écart, le test ne
            # distinguerait pas un compte juste d'un compte qui recopie le total.
            dict.fromkeys(keys if culture != cultures[-1] else keys[:1000], "x")
        )
        for culture in cultures
    }
    paths = [*files, "trads/accueil/contexte.yaml"]
    reads: list[str] = []

    async def read(path: str) -> str | None:
        reads.append(path)
        return files.get(path)

    contexts = await file_contexts(read, paths, cultures)
    coverage = rolled_up(contexts, cultures[0], tuple(cultures), branch="b", threshold=50)
    by_culture = {r.culture: r for r in coverage.cultures}

    assert coverage.keys == 2000
    assert by_culture[cultures[-1]].translated == 1000
    assert by_culture[cultures[0]].translated == 2000
    # Dix fichiers de culture plus `contexte.yaml`, et rien de plus.
    assert len(reads) == 11
    assert sorted(reads) == sorted(paths)
