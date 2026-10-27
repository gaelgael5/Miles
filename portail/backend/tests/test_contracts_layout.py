from __future__ import annotations

import pytest

from miles.contracts.layout import (
    ContractMeta,
    VersionImport,
    checked_slug,
    meta_text,
    read_meta,
    slugs_in,
    versions_in,
)
from miles.workspaces.model import WorkspaceInputError, checked_label


@pytest.mark.parametrize(
    "label",
    ["Suivi : demandes # v2", 'Guillemets "doubles" et \\ barre', "Évènements — colis"],
)
def test_label_is_written_so_that_it_reads_back_unchanged(label: str) -> None:
    meta = ContractMeta("suivi", label, "interne")

    assert read_meta(meta_text(meta)) == meta


def test_contract_imported_before_labels_takes_its_slug_as_label() -> None:
    assert read_meta("slug: suivi\nsens: externe\n") == ContractMeta("suivi", "suivi", "externe")


@pytest.mark.parametrize(("stored", "expected"), [("sortant", "externe"), ("entrant", "interne")])
def test_declaration_stored_before_the_rename_reads_as_its_current_direction(
    stored: str, expected: str
) -> None:
    assert read_meta(f"slug: suivi\nsens: {stored}\n") == ContractMeta("suivi", "suivi", expected)


@pytest.mark.parametrize(("stored", "canonical"), [("sortant", "externe"), ("entrant", "interne")])
def test_rewriting_a_declaration_stored_before_the_rename_poses_the_current_direction(
    stored: str, canonical: str
) -> None:
    """La relecture-réécriture migre le fichier : c'est tout le chemin de reprise prévu."""
    meta = read_meta(f"slug: suivi\nsens: {stored}\n")

    assert meta is not None
    assert f"sens: {canonical}\n" in meta_text(meta)
    assert f"sens: {stored}\n" not in meta_text(meta)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "- a\n",
        "slug: suivi\nsens: lateral\n",
        "slug: suivi\nlabel: [x]\nsens: interne\n",
        # Un sens non textuel vient d'une retouche hors de Miles : il rend la
        # déclaration illisible, il ne fait pas tomber l'écran des contrats.
        "slug: suivi\nsens: [x]\n",
        "slug: suivi\nsens: {a: b}\n",
    ],
)
def test_unreadable_declaration_is_none(text: str | None) -> None:
    assert read_meta(text) is None


def test_versions_are_listed_in_number_order_and_strays_ignored() -> None:
    paths = [
        "contracts/suivi/contract.yaml",
        "contracts/suivi/v10.yaml",
        "contracts/suivi/v2.yaml",
        "contracts/suivi/v0.yaml",
        "contracts/suivi/notes.yaml",
        "contracts/autre/v1.yaml",
        "contracts/autre/contract.yaml",
        "contracts/suivi/sous/v3.yaml",
    ]

    assert versions_in(paths, "suivi") == [2, 10]
    assert slugs_in(paths) == ["autre", "suivi"]


@pytest.mark.parametrize(
    ("label", "reason"),
    [("   ", "vide"), ("x" * 121, None), ("deux\nlignes", None), ("bip\x1b[31m", None)],
)
def test_label_refusals_name_the_field(label: str, reason: str | None) -> None:
    with pytest.raises(WorkspaceInputError) as caught:
        checked_label(label)

    assert (caught.value.field, caught.value.reason) == ("label", reason)


def test_label_and_slug_are_trimmed() -> None:
    assert (checked_label("  Suivi  "), checked_slug(" suivi ")) == ("Suivi", "suivi")
    with pytest.raises(WorkspaceInputError):
        checked_slug("Suivi!")


def test_deposits_are_written_and_read_back_with_the_declaration() -> None:
    deposit = VersionImport("2026-10-22T08:00:00+00:00", "Gaël via Miles <g@x.miles.invalid>")
    meta = ContractMeta("suivi", "Suivi", "externe").with_import(2, deposit)

    back = read_meta(meta_text(meta))

    assert back == meta
    assert back is not None and back.imported(2) == deposit and back.imported(1) is None
    # Un dépôt ne change pas l'identité déclarée : le rejeu de la déclaration reste égal.
    assert back.declaration() == ("suivi", "Suivi", "externe")


@pytest.mark.parametrize(
    "versions",
    ["versions: [1]\n", "versions:\n  un: {imported_at: x, by: y}\n", "versions:\n  1: {by: y}\n"],
)
def test_malformed_deposits_make_the_declaration_unreadable(versions: str) -> None:
    assert read_meta("slug: suivi\nsens: externe\n" + versions) is None
