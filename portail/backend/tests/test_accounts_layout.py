from __future__ import annotations

from collections.abc import Awaitable, Callable

from miles.accounts.layout import (
    PATH,
    AccountReference,
    ReferenceProblem,
    read_reference,
    reference_text,
)
from miles.accounts.service import ReferenceState, file_state


def test_the_file_sits_at_the_root_like_the_storages_it_designates() -> None:
    assert PATH == "comptes/reference.yaml"


def test_what_is_written_is_read_back_unchanged() -> None:
    text = reference_text(AccountReference("comptes-pudo"))

    assert text == 'storage: "comptes-pudo"\n'
    assert read_reference(text) == AccountReference("comptes-pudo")


def test_the_model_is_never_written_in_the_file() -> None:
    # La garde du 31/10/2026 : le storage déclare déjà son modèle, et le recopier ici
    # ferait une seconde source de vérité qui dériverait sans que rien ne le signale.
    assert "modele" not in reference_text(AccountReference("comptes"))
    assert "model" not in reference_text(AccountReference("comptes"))


def test_a_file_written_by_hand_is_read() -> None:
    assert read_reference("storage: comptes\n") == AccountReference("comptes")


def test_surrounding_spaces_are_dropped() -> None:
    assert read_reference('storage: "  comptes  "\n') == AccountReference("comptes")


def test_a_key_the_file_does_not_know_makes_it_unreadable() -> None:
    # Refusé plutôt qu'ignoré : une clé inconnue est soit une faute de frappe sur une clé
    # attendue, soit un réglage qu'une version plus récente de Miles comprend. Dans les
    # deux cas, l'ignorer ferait appliquer un réglage qui n'est pas celui écrit.
    assert read_reference("storage: comptes\ncanal: sms\n") is None


def test_a_missing_or_empty_storage_makes_it_unreadable() -> None:
    assert read_reference("libelle: Comptes\n") is None
    assert read_reference('storage: ""\n') is None
    assert read_reference('storage: "   "\n') is None


def test_a_storage_that_is_not_a_string_makes_it_unreadable() -> None:
    assert read_reference("storage:\n  - comptes\n") is None
    assert read_reference("storage: 12\n") is None


def test_a_document_that_is_not_a_mapping_makes_it_unreadable() -> None:
    assert read_reference("- comptes\n") is None
    assert read_reference("comptes\n") is None


def test_broken_yaml_is_unreadable_rather_than_raising() -> None:
    # Le fichier vient du dépôt : il peut être n'importe quoi, et la lecture d'une branche
    # ne doit pas tomber sur l'écriture d'un tiers.
    assert read_reference("storage: [\n") is None


# --- Les quatre états que la branche peut porter (service.file_state) ---


def _branch(files: dict[str, str]) -> Callable[[str], Awaitable[str | None]]:
    """Une branche réduite à ses fichiers : tout ce dont `file_state` a besoin."""

    async def read(path: str) -> str | None:
        return files.get(path)

    return read


COMPTES = 'nom: "comptes"\nlibelle: "Comptes"\nmodele: "shared/compte"\ncle:\n  - "$.id"\n'


async def test_a_branch_without_the_file_declares_nothing_and_that_is_not_a_defect() -> None:
    assert await file_state(_branch({})) == ReferenceState(None, None, None)


async def test_a_healthy_reference_carries_the_model_read_from_the_storage() -> None:
    # Le modèle vient du STORAGE, pas du fichier de référence : c'est la garde du 31/10.
    state = await file_state(
        _branch({PATH: 'storage: "comptes"\n', "storages/comptes.yaml": COMPTES})
    )

    assert state == ReferenceState(AccountReference("comptes"), "shared/compte", None)


async def test_an_unreadable_file_is_named_instead_of_counting_as_nothing_declared() -> None:
    state = await file_state(_branch({PATH: "storage: [\n"}))

    assert state.reference is None
    assert state.problem == ReferenceProblem(PATH, "fichier_illisible")


async def test_a_storage_that_vanished_keeps_the_reference_and_names_the_defect() -> None:
    # Le réglage est RENDU : sans lui, l'écran afficherait « aucune référence » et
    # effacerait en silence un réglage qu'il faut corriger.
    state = await file_state(_branch({PATH: 'storage: "comptes"\n'}))

    assert state.reference == AccountReference("comptes")
    assert state.model is None
    assert state.problem == ReferenceProblem(PATH, "storage_inconnu", "comptes")


async def test_a_storage_broken_outside_miles_is_told_apart_from_a_missing_one() -> None:
    # Deux causes distinctes, deux codes : « disparu » et « illisible » ne se corrigent
    # pas de la même façon, et un code unique renverrait au mauvais geste.
    state = await file_state(_branch({PATH: 'storage: "comptes"\n', "storages/comptes.yaml": "["}))

    assert state.reference == AccountReference("comptes")
    assert state.problem == ReferenceProblem(PATH, "storage_illisible", "comptes")
