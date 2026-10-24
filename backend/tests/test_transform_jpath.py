from __future__ import annotations

import pytest

from miles.transform.jpath import path_keys, property_keys, read_path


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("$.a.b", ("a", "b")),
        ("$.l[2].c", ("l", 2, "c")),
        ("$.l[*]", None),
        ("@.a", None),
        ("x", None),
    ],
)
def test_single_paths_are_read_by_the_engine(text: str, keys: tuple[str | int, ...] | None) -> None:
    assert path_keys(text) == keys


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("$.adresse.ville", ["adresse", "ville"]),
        # Un indice ne se résout pas contre un schéma : on descend par nom de propriété.
        ("$.l[2].c", None),
        ("$.l[*]", None),
        ("$..a", None),
    ],
)
def test_property_paths_refuse_an_array_index(text: str, keys: list[str] | None) -> None:
    assert property_keys(text) == keys


def test_what_is_not_a_path_is_not_read_as_one() -> None:
    assert read_path("{ }") is None
    assert read_path("$.a") is not None
