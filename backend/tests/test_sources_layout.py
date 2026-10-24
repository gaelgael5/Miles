from __future__ import annotations

from dataclasses import replace

import pytest

from miles.sources.layout import SourceDoc, form_problems, read_source, source_text

# Depuis la séparation du 24/10/2026 (844f15ad), une source ne dit que COMMENT on remplit
# un storage : plus de modèle, plus de clé, plus de propriétés filtrables.
DOC = SourceDoc("comptes", "comptes", "$.accounts[*]", "comptes-import", True, False)


def test_declaration_is_written_and_reads_back_unchanged() -> None:
    text = source_text(DOC)

    assert read_source(text) == DOC
    assert source_text(DOC) == text


@pytest.mark.parametrize(
    "text",
    [None, "- a\n", 'nom: "x"\ninconnue: 1\n', 'nom: "x"\nstorage: 3\n', "nom: [\n"],
    ids=["absente", "liste", "cle-inconnue", "type", "illisible"],
)
def test_malformed_declaration_is_unreadable(text: str | None) -> None:
    assert read_source(text) is None


def test_a_source_of_the_old_shape_is_not_taken_up_in_silence() -> None:
    """Critère 21 : `modele` / `cle` / `filtrables` ne sont plus des clés de la source.

    Les deviner reviendrait à choisir en silence ce qui est stocké ; la déclaration se lit
    donc comme illisible, et la validation de branche dit quoi faire.
    """
    ancienne = (
        'nom: "comptes"\nmodele: "shared/compte"\ndecoupage: "$.accounts[*]"\n'
        'cle:\n  - "$.accountId"\nchaine: "comptes-import"\n'
        "mode_gros_fichier: true\ntransaction_unifiee: false\nfiltrables: []\n"
    )

    assert read_source(ancienne) is None


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


def test_a_source_without_a_storage_is_refused_and_named() -> None:
    """Critère 17 : jamais un repli silencieux sur un storage deviné."""
    problems = form_problems(replace(DOC, storage="  "))

    assert [(p.path, p.code) for p in problems] == [("storage", "storage_absent")]


def test_form_problems_are_all_reported() -> None:
    bad = SourceDoc("Comptes!", "Pas Un Nom", "", "x", False, False)

    assert {(p.path, p.code) for p in form_problems(bad)} == {
        ("nom", "nom_invalide"),
        ("storage", "nom_invalide"),
        ("decoupage", "decoupage_absent"),
    }
