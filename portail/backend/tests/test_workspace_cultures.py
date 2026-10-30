from __future__ import annotations

import pytest

from miles.workspaces.cultures import (
    DefaultCultureIncompleteError,
    MissingDefaultCultureError,
    WorkspaceCultures,
    checked_culture,
    cultures_from_rows,
)
from miles.workspaces.model import WorkspaceInputError


def test_cultures_from_rows_puts_the_default_apart_from_the_additional_ones() -> None:
    rows = [
        {"culture": "fr-FR", "is_default": True},
        {"culture": "ar-MA", "is_default": False},
        {"culture": "th-TH", "is_default": False},
    ]

    assert cultures_from_rows(rows) == WorkspaceCultures("fr-FR", ("ar-MA", "th-TH"))


def test_cultures_all_starts_with_the_default_one() -> None:
    """La saisie montre la culture par défaut en premier (critère 2)."""
    assert WorkspaceCultures("fr-FR", ("ar-MA",)).all == ("fr-FR", "ar-MA")


def test_cultures_from_rows_without_a_default_is_named_not_returned_empty() -> None:
    with pytest.raises(MissingDefaultCultureError, match="culture_defaut_absente"):
        cultures_from_rows([{"culture": "ar-MA", "is_default": False}])


def test_cultures_from_rows_no_row_at_all_is_the_same_refusal() -> None:
    with pytest.raises(MissingDefaultCultureError):
        cultures_from_rows([])


@pytest.mark.parametrize("code", ["fr", "fr-FR", "ar-MA", "zh-Hans-CN", "es-419"])
def test_checked_culture_accepts_a_bcp47_code(code: str) -> None:
    assert checked_culture(code) == code


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/passwd",
        "fr-FR/../../secret",
        "..",
        ".",
        "fr_FR",
        "fr FR",
        "FR",
        "",
        "fr-FR\x00",
        "fr-FR\n",
    ],
)
def test_checked_culture_refuses_what_could_leave_the_trads_directory(hostile: str) -> None:
    """Le code devient un segment de `trads/<contexte>/<culture>.yaml`, et le comptage de
    ce qui manque a lieu avant toute écriture — donc avant que la base n'ait pu trancher."""
    with pytest.raises(WorkspaceInputError) as refus:
        checked_culture(hostile)

    assert refus.value.field == "culture"
    assert refus.value.reason == "forme"


def test_checked_culture_names_the_field_of_the_screen_that_was_filled() -> None:
    with pytest.raises(WorkspaceInputError) as refus:
        checked_culture("pas une culture", "default_culture")

    assert refus.value.field == "default_culture"


def test_incomplete_default_culture_carries_the_count_so_the_screen_can_say_the_work() -> None:
    refus = DefaultCultureIncompleteError("ar-MA", 12)

    assert (refus.code, refus.culture, refus.missing) == ("culture_defaut_incomplete", "ar-MA", 12)
