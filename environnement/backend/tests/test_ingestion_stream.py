"""La lecture en flux d'un document déposé : les deux passes, et ce qu'elles refusent."""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    DOCUMENT_TOO_DEEP,
    ITEMS_PATH_ABSENT,
    ITEMS_PATH_NOT_ARRAY,
    MAX_DEPTH,
    METADATA_TOO_LARGE,
    DocumentUnreadable,
)
from environnement.ingestion.stream import file_iter_items, file_read_metadata

BUDGET = 1_000


def _write(tmp_path: Path, content: str) -> Path:
    document = tmp_path / "depot.json"
    document.write_text(content, encoding="utf-8")
    return document


def _document(tmp_path: Path, value: Any) -> Path:
    return _write(tmp_path, json.dumps(value))


def test_the_items_of_the_split_array_are_read_one_by_one(tmp_path: Path) -> None:
    document = _document(tmp_path, {"root": [{"a": 1}, {"a": 2}, {"a": 3}]})

    assert list(file_iter_items(document, ("root",))) == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_a_document_that_is_itself_the_array_is_read_without_keys(tmp_path: Path) -> None:
    document = _document(tmp_path, [{"a": 1}])

    assert list(file_iter_items(document, ())) == [{"a": 1}]


def test_an_index_in_the_split_selects_that_element_alone(tmp_path: Path) -> None:
    """Le point de la lecture sans préfixe : `[0]` ne doit pas prendre les items de `[1]`."""
    document = _document(tmp_path, {"lots": [{"sites": [{"a": 1}]}, {"sites": [{"a": 2}]}]})

    assert list(file_iter_items(document, ("lots", 0, "sites"))) == [{"a": 1}]
    assert list(file_iter_items(document, ("lots", 1, "sites"))) == [{"a": 2}]


def test_an_empty_array_is_an_ingestion_of_zero_item_and_not_an_error(tmp_path: Path) -> None:
    document = _document(tmp_path, {"root": []})

    assert list(file_iter_items(document, ("root",))) == []


def test_items_keep_their_whole_shape_including_nested_containers(tmp_path: Path) -> None:
    item = {"a": [1, {"b": None}], "c": {"d": [True, 2.5]}}
    document = _document(tmp_path, {"root": [item]})

    assert list(file_iter_items(document, ("root",))) == [item]


def test_metadata_placed_after_the_array_are_still_read(tmp_path: Path) -> None:
    """Le critère 6, et la preuve de la double passe : en SAX pur, cet en-tête arrive trop
    tard."""
    document = _write(tmp_path, '{"root": [{"a": 1}], "genere_le": "2026-11-04", "total": 1}')

    assert file_read_metadata(document, ("root",), BUDGET) == {
        "genere_le": "2026-11-04",
        "total": 1,
    }


def test_metadata_placed_before_the_array_are_read_the_same_way(tmp_path: Path) -> None:
    document = _write(tmp_path, '{"genere_le": "2026-11-04", "root": [{"a": 1}]}')

    assert file_read_metadata(document, ("root",), BUDGET) == {"genere_le": "2026-11-04"}


def test_a_document_with_nothing_but_its_items_has_no_metadata(tmp_path: Path) -> None:
    """None et non un objet vide : « aucun en-tête » ne se dit pas « un en-tête sans
    champ »."""
    assert file_read_metadata(_document(tmp_path, {"root": [{"a": 1}]}), ("root",), BUDGET) is None
    assert file_read_metadata(_document(tmp_path, [{"a": 1}]), (), BUDGET) is None


def test_metadata_keep_the_shape_around_a_nested_items_array(tmp_path: Path) -> None:
    document = _document(tmp_path, {"lots": [{"nom": "a", "sites": [{"x": 1}]}], "total": 1})

    assert file_read_metadata(document, ("lots", 0, "sites"), BUDGET) == {
        "lots": [{"nom": "a"}],
        "total": 1,
    }


def test_metadata_beyond_the_budget_are_refused_rather_than_truncated(tmp_path: Path) -> None:
    document = _document(tmp_path, {"root": [], "entete": list(range(50))})

    with pytest.raises(DocumentUnreadable) as refus:
        file_read_metadata(document, ("root",), 10)

    assert refus.value.code == METADATA_TOO_LARGE


def test_a_split_that_designates_nothing_in_the_document_is_refused_by_its_path(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path, {"autre": [{"a": 1}]})

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",)))

    assert (refus.value.code, refus.value.detail) == (ITEMS_PATH_ABSENT, "$.root[*]")


@pytest.mark.parametrize(
    ("value", "keys"),
    [
        ({"root": {"a": 1}}, ("root",)),
        ({"root": 12}, ("root",)),
        ({"lots": [{"sites": 1}]}, ("lots", 0, "sites")),
    ],
    ids=["objet", "scalaire", "imbrique"],
)
def test_a_split_that_designates_something_other_than_an_array_is_refused(
    tmp_path: Path, value: Any, keys: tuple[str | int, ...]
) -> None:
    """Critère 4 : l'erreur nomme le jpath, et rien n'est émis."""
    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(_document(tmp_path, value), keys))

    assert refus.value.code == ITEMS_PATH_NOT_ARRAY


def test_an_index_beyond_the_array_is_refused_rather_than_read_as_empty(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path, {"lots": [{"sites": [{"a": 1}]}]})

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("lots", 3, "sites")))

    assert refus.value.code == ITEMS_PATH_ABSENT


def test_a_file_truncated_mid_array_yields_the_items_read_before_the_incident(
    tmp_path: Path,
) -> None:
    """Critères 7 et 8 : l'appelant doit pouvoir compter ce qui a été lu avant l'incident."""
    document = _write(tmp_path, '{"root": [{"a": 1}, {"a": 2}, {"a":')
    lus = []

    with pytest.raises(DocumentUnreadable) as refus:
        for item in file_iter_items(document, ("root",)):
            lus.append(item)

    assert lus == [{"a": 1}, {"a": 2}]
    assert refus.value.code == DOCUMENT_INVALID


def test_a_truncated_file_does_not_make_the_metadata_pass_refuse(tmp_path: Path) -> None:
    """Écart assumé : refuser ici rendrait le critère 8 inatteignable."""
    assert file_read_metadata(_write(tmp_path, '{"root": [{"a": 1'), ("root",), BUDGET) is None


def test_a_malformed_document_is_refused_with_the_position_of_the_incident(
    tmp_path: Path,
) -> None:
    document = _write(tmp_path, '{"root": [{"a": oui}]}')

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",)))

    assert refus.value.code == DOCUMENT_INVALID
    assert refus.value.detail


@pytest.mark.parametrize("depth", [0, 1, 20], ids=["profondeur-0", "profondeur-1", "profondeur-20"])
def test_a_nesting_within_the_bound_is_read(tmp_path: Path, depth: int) -> None:
    item: Any = {"a": 1}
    for _ in range(depth):
        item = {"n": item}
    document = _document(tmp_path, {"root": [item]})

    assert list(file_iter_items(document, ("root",))) == [item]


def test_a_nesting_beyond_the_bound_is_refused_rather_than_overflowing_the_stack(
    tmp_path: Path,
) -> None:
    """Rendu, jamais subi : un débordement de pile tomberait le service."""
    document = _write(
        tmp_path, '{"root": [' + '{"n": ' * (MAX_DEPTH + 5) + "1" + "}" * (MAX_DEPTH + 5) + "]}"
    )

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",)))

    assert refus.value.code == DOCUMENT_TOO_DEEP


def test_a_document_much_larger_than_memory_is_never_held_whole(tmp_path: Path) -> None:
    """Critère 1, MESURÉ : le pic d'allocation doit rester loin de la taille du fichier.

    Mesuré et non déduit du fait qu'un parseur en flux est employé : c'est précisément le
    genre de promesse qu'une construction intermédiaire annule sans que rien ne le dise.
    """
    document = tmp_path / "gros.json"
    item = json.dumps({"cle": "x" * 500, "n": 1})
    with document.open("w", encoding="utf-8") as handle:
        handle.write('{"root": [')
        handle.write(",".join([item] * 20_000))
        handle.write('], "total": 20000}')
    taille = document.stat().st_size

    tracemalloc.start()
    compte = sum(1 for _ in file_iter_items(document, ("root",)))
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert compte == 20_000
    assert taille > 10_000_000
    assert pic < taille // 10
