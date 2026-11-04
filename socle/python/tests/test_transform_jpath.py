from __future__ import annotations

import pytest

from miles_socle.transform.jpath import (
    SplitRefusal,
    StreamSplit,
    path_keys,
    property_keys,
    read_path,
    read_stream_split,
)


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


@pytest.mark.parametrize(
    ("split", "keys"),
    [
        ("$.root[*]", ("root",)),
        ("$[*]", ()),
        ("$.a.b[*]", ("a", "b")),
        ("$.lots[0].sites[*]", ("lots", 0, "sites")),
    ],
    ids=["racine-nommee", "document-tableau", "deux-noms", "indice"],
)
def test_a_streamable_split_yields_the_keys_of_its_array(
    split: str, keys: tuple[str | int, ...]
) -> None:
    """Le joker final n'entre pas dans les clés : il désigne ce qu'on émet, pas où l'on va."""
    lu = read_stream_split(split)

    assert lu == StreamSplit(keys)


@pytest.mark.parametrize(
    ("split", "code", "detail"),
    [
        (
            "$.sites[?(@.actif == true)]",
            "non_streamable",
            "un filtre exige l'item entier avant de le garder",
        ),
        ("$..sites[*]", "non_streamable", "descente « .. » non bornée"),
        ("$.sites[*].lignes[*]", "non_streamable", "le joker doit terminer le chemin"),
        ("$.sites", "non_streamable", "le chemin doit finir par [*]"),
        ("$", "non_streamable", "le chemin doit désigner un tableau"),
        ("pas un jpath", "jpath_illisible", "pas un jpath"),
    ],
    ids=["filtre", "descente", "joker-au-milieu", "pas-de-tableau", "racine-seule", "illisible"],
)
def test_a_split_that_would_need_a_step_back_is_refused_with_its_reason(
    split: str, code: str, detail: str
) -> None:
    lu = read_stream_split(split)

    assert lu == SplitRefusal(code, detail)
