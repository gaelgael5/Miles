from __future__ import annotations

import re

import pytest

from miles.workshop.trads import (
    TradsFileError,
    contexts_in,
    culture_file,
    cultures_in,
    file_missing_keys,
    keys_of,
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
