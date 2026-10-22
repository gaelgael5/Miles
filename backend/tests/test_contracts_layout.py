from __future__ import annotations

import pytest

from miles.contracts.layout import (
    ContractMeta,
    checked_label,
    checked_slug,
    meta_text,
    read_meta,
    slugs_in,
    versions_in,
)
from miles.workspaces.model import WorkspaceInputError


@pytest.mark.parametrize(
    "label",
    ["Suivi : demandes # v2", 'Guillemets "doubles" et \\ barre', "Évènements — colis"],
)
def test_label_is_written_so_that_it_reads_back_unchanged(label: str) -> None:
    meta = ContractMeta("suivi", label, "entrant")

    assert read_meta(meta_text(meta)) == meta


def test_contract_imported_before_labels_takes_its_slug_as_label() -> None:
    assert read_meta("slug: suivi\nsens: sortant\n") == ContractMeta("suivi", "suivi", "sortant")


@pytest.mark.parametrize(
    "text",
    [None, "", "- a\n", "slug: suivi\nsens: lateral\n", "slug: suivi\nlabel: [x]\nsens: entrant\n"],
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
