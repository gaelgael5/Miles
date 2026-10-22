from __future__ import annotations

from dataclasses import replace

import pytest

from miles.sources.layout import (
    Filterable,
    SourceDoc,
    form_problems,
    path_keys,
    read_source,
    source_text,
)

DOC = SourceDoc(
    "comptes",
    "shared/compte",
    "$.accounts[*]",
    ("$.accountId",),
    "comptes-import",
    True,
    False,
    (Filterable("code", "$.code"), Filterable("ville", "$.adresse.ville")),
)


def test_declaration_is_written_and_reads_back_unchanged() -> None:
    text = source_text(DOC)

    assert read_source(text) == DOC
    assert source_text(DOC) == text


@pytest.mark.parametrize(
    "text",
    [None, "- a\n", 'nom: "x"\ninconnue: 1\n', 'nom: "x"\nmodele: 3\n', "nom: [\n"],
    ids=["absente", "liste", "cle-inconnue", "type", "illisible"],
)
def test_malformed_declaration_is_unreadable(text: str | None) -> None:
    assert read_source(text) is None


@pytest.mark.parametrize(
    "split", ["$.accounts[*]", "$[*]", "$.data.items[*]", "$.pages[0].items[*]"]
)
def test_streamable_split_is_accepted(split: str) -> None:
    assert form_problems(replace(DOC, split=split)) == []


@pytest.mark.parametrize(
    ("split", "detail"),
    [
        ("$.accounts[?(@.actif == true)]", "un filtre exige l'item entier avant de le garder"),
        ("$..accounts[*]", "descente « .. » non bornée"),
        ("$.accounts[*].lignes[*]", "le joker doit terminer le chemin"),
        ("$.accounts", "le chemin doit finir par [*]"),
    ],
    ids=["filtre", "descente", "joker-au-milieu", "pas-de-tableau"],
)
def test_split_that_cannot_be_read_as_a_stream_is_refused_with_its_reason(
    split: str, detail: str
) -> None:
    problems = form_problems(replace(DOC, split=split))

    assert [(p.path, p.code, p.detail) for p in problems] == [
        ("decoupage", "non_streamable", detail)
    ]


def test_form_problems_are_all_reported() -> None:
    bad = SourceDoc(
        "Comptes!",
        "compte",
        "",
        (),
        "x",
        False,
        False,
        (Filterable("code", "$.code"), Filterable("code", "$.code")),
    )

    assert {(p.path, p.code) for p in form_problems(bad)} == {
        ("nom", "nom_invalide"),
        ("modele", "modele_invalide"),
        ("decoupage", "decoupage_absent"),
        ("cle", "cle_vide"),
        ("filtrables[0].nom", "nom_invalide"),
        ("filtrables[1].nom", "nom_invalide"),
        ("filtrables[0].jpath", "jpath_double"),
        ("filtrables[1].jpath", "jpath_double"),
    }


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
