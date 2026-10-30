from __future__ import annotations

import re

import pytest

from miles.workshop.trads import (
    TradsFileError,
    checked_context,
    checked_label,
    context_text,
    contexts_in,
    culture_file,
    cultures_in,
    file_contexts,
    file_missing_keys,
    keys_of,
    label_of,
)

PATHS = [
    "manifest.yaml",
    "trads/accueil/fr-FR.yaml",
    "trads/accueil/ar-MA.yaml",
    "trads/erreurs/fr-FR.yaml",
    "trads/vide/.gitkeep",
    "domains/retrait/messages/demande.yaml",
]
FILES = {
    "trads/accueil/fr-FR.yaml": "titre: Bonjour\nadieu: Au revoir\n",
    "trads/accueil/ar-MA.yaml": "titre: مرحبا\n",
    "trads/erreurs/fr-FR.yaml": "refus: Refusé\n",
}


async def _read(path: str) -> str | None:
    return FILES.get(path)


def test_contexts_in_lists_directories_of_trads_including_the_empty_one() -> None:
    assert contexts_in(PATHS) == ["accueil", "erreurs", "vide"]


def test_contexts_in_ignores_the_rest_of_the_tree() -> None:
    assert contexts_in(["domains/retrait/messages/x.yaml", "trads/.gitkeep"]) == []


def test_cultures_in_lists_the_culture_files_of_one_context() -> None:
    assert cultures_in(PATHS, "accueil") == ["ar-MA", "fr-FR"]
    assert cultures_in(PATHS, "vide") == []


def test_cultures_in_ignores_a_file_nested_deeper_than_the_context() -> None:
    assert cultures_in(["trads/accueil/sous/fr-FR.yaml"], "accueil") == []


def test_keys_of_reads_a_flat_mapping() -> None:
    assert keys_of("p", "titre: Bonjour\nadieu: Au revoir\n") == {"titre", "adieu"}


@pytest.mark.parametrize("content", [None, "", "\n", "# rien\n"])
def test_keys_of_empty_file_has_no_key(content: str | None) -> None:
    """Une culture qu'on vient d'ajouter n'a aucune valeur : ce n'est pas une erreur."""
    assert keys_of("p", content) == set()


def test_keys_of_unreadable_yaml_raises_and_names_the_file() -> None:
    with pytest.raises(TradsFileError, match=re.escape("trads/accueil/fr-FR.yaml")) as refus:
        keys_of("trads/accueil/fr-FR.yaml", "titre: [non fermé\n")

    assert refus.value.reason == "yaml illisible"


@pytest.mark.parametrize("content", ["- titre\n- adieu\n", "juste une chaîne\n", "42\n"])
def test_keys_of_non_mapping_raises(content: str) -> None:
    """Pas de repli sur « zéro clé » : il rendrait une couverture fausse, donc un
    changement de culture par défaut accepté à tort."""
    with pytest.raises(TradsFileError, match="mappe"):
        keys_of("p", content)


def test_culture_file_is_one_file_per_context_and_culture() -> None:
    assert culture_file("accueil", "fr-FR") == "trads/accueil/fr-FR.yaml"


async def test_file_missing_keys_counts_what_a_culture_lacks_across_contexts() -> None:
    # ar-MA porte `titre` mais pas `adieu` dans « accueil », et rien dans « erreurs ».
    assert await file_missing_keys(_read, PATHS, "ar-MA") == 2


async def test_file_missing_keys_zero_for_the_culture_that_declares_every_key() -> None:
    assert await file_missing_keys(_read, PATHS, "fr-FR") == 0


async def test_file_missing_keys_counts_every_key_for_a_culture_without_any_file() -> None:
    assert await file_missing_keys(_read, PATHS, "th-TH") == 3


async def test_file_missing_keys_zero_when_the_branch_has_no_trads_at_all() -> None:
    """État d'un dépôt avant tout contexte : le changement de culture par défaut passe."""
    assert await file_missing_keys(_read, ["manifest.yaml"], "th-TH") == 0


# --- Contextes (story 623898d1) ---


def test_cultures_in_ignores_the_context_metadata_file() -> None:
    """Filtré sur la FORME d'un code de culture : `contexte` n'en est pas un."""
    paths = ["trads/accueil/contexte.yaml", "trads/accueil/fr-FR.yaml", "trads/accueil/notes.yaml"]

    assert cultures_in(paths, "accueil") == ["fr-FR"]


@pytest.mark.parametrize("name", ["accueil", "a", "mes-ecrans", "lot_2", "x9"])
def test_checked_context_accepts_a_directory_slug(name: str) -> None:
    assert checked_context(name) == name


@pytest.mark.parametrize(
    "hostile",
    ["../evasion", "accueil/..", "a/b", ".", "..", "Accueil", "mes écrans", "été", "", "ok\n"],
)
def test_checked_context_refuses_what_could_leave_the_trads_directory(hostile: str) -> None:
    with pytest.raises(ValueError, match="nom de contexte invalide"):
        checked_context(hostile)


def test_checked_label_trims_and_keeps_accents_and_non_latin_glyphs() -> None:
    assert checked_label("  Écrans d'accueil  ") == "Écrans d'accueil"
    assert checked_label("หน้าแรก") == "หน้าแรก"


@pytest.mark.parametrize("hostile", ["", "   ", "sur\ndeux lignes", "x" * 121, "nul\x00"])
def test_checked_label_refuses_what_would_break_a_display(hostile: str) -> None:
    with pytest.raises(ValueError, match="libellé de contexte invalide"):
        checked_label(hostile)


def test_context_text_reads_back_the_label_unchanged() -> None:
    text = context_text("Écrans d'accueil — مرحبا")

    assert label_of("p", text, "accueil") == "Écrans d'accueil — مرحبا"


def test_label_of_falls_back_on_the_technical_name_when_no_metadata() -> None:
    """Un répertoire créé à la main apparaît dans la liste (critère 9)."""
    assert label_of("p", None, "accueil") == "accueil"


@pytest.mark.parametrize("content", ["label: ''\n", "label: '   '\n", "label: 42\n", "autre: x\n"])
def test_label_of_falls_back_when_the_declared_label_is_unusable(content: str) -> None:
    assert label_of("p", content, "accueil") == "accueil"


def test_label_of_unreadable_metadata_is_named() -> None:
    with pytest.raises(TradsFileError, match="illisible"):
        label_of("p", "label: [non fermé\n", "accueil")


def test_label_of_non_mapping_metadata_is_named() -> None:
    with pytest.raises(TradsFileError, match="mappe"):
        label_of("p", "- accueil\n", "accueil")


async def test_file_contexts_counts_keys_and_coverage_per_workspace_culture() -> None:
    contexts = await file_contexts(_read, PATHS, ["fr-FR", "ar-MA", "th-TH"])

    assert [(c.name, c.keys) for c in contexts] == [("accueil", 2), ("erreurs", 1), ("vide", 0)]
    accueil = contexts[0]
    assert accueil.translated == {"fr-FR": 2, "ar-MA": 1, "th-TH": 0}
    # Toutes les cultures du dépôt sont au workspace : rien d'obsolète.
    assert accueil.obsolete == {}
    # Pas de fichier de métadonnées dans le jeu : le nom technique fait office de libellé.
    assert accueil.label == "accueil"


async def test_file_contexts_empty_context_is_zero_on_zero_not_fully_covered() -> None:
    """Zéro clé traduite sur zéro clé n'est pas une bonne nouvelle (critère 8)."""
    vide = (await file_contexts(_read, PATHS, ["fr-FR"]))[2]

    assert (vide.name, vide.keys, vide.translated) == ("vide", 0, {"fr-FR": 0})
    assert vide.obsolete == {}


async def test_file_contexts_ignores_a_culture_of_the_repository_left_out_of_the_workspace() -> (
    None
):
    """ar-MA a un fichier mais n'est plus du workspace : hors couverture, clés comptées."""
    accueil = (await file_contexts(_read, PATHS, ["fr-FR"]))[0]

    assert accueil.keys == 2
    assert accueil.translated == {"fr-FR": 2}
    # ar-MA n'est plus du workspace, et son fichier porte encore une valeur : c'est ce
    # que l'écran doit pouvoir proposer de nettoyer.
    assert accueil.obsolete == {"ar-MA": 1}


async def test_file_contexts_counts_the_values_each_obsolete_culture_still_holds() -> None:
    """Retirer une culture garde ses fichiers, exprès. Sans ce compte, personne ne saurait
    qu'ils sont encore là, ni ce qu'ils pèsent."""
    contexts = await file_contexts(_read, PATHS, ["ar-MA"])

    accueil = contexts[0]
    assert accueil.obsolete == {"fr-FR": 2}
    assert accueil.translated == {"ar-MA": 1}
