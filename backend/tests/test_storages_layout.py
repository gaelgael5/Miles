from __future__ import annotations

from dataclasses import replace

import pytest

from miles.storages.layout import (
    Indexable,
    StorageDoc,
    form_problems,
    names_in,
    read_storage,
    storage_text,
)

DOC = StorageDoc(
    "sites",
    "Sites",
    "pudo/site",
    ("$.Id",),
    (Indexable("ville", "$.adresse.ville"),),
)


def test_declaration_is_written_and_reads_back_unchanged() -> None:
    text = storage_text(DOC)

    assert read_storage(text) == DOC
    assert storage_text(DOC) == text


def test_a_storage_without_any_indexable_property_round_trips() -> None:
    bare = replace(DOC, indexables=())

    assert read_storage(storage_text(bare)) == bare


@pytest.mark.parametrize(
    "text",
    [None, "- a\n", 'nom: "x"\ninconnue: 1\n', 'nom: "x"\nlibelle: 3\n', "nom: [\n"],
    ids=["absente", "liste", "cle-inconnue", "type", "illisible"],
)
def test_malformed_declaration_is_unreadable(text: str | None) -> None:
    assert read_storage(text) is None


def test_a_jpath_survives_the_yaml_round_trip() -> None:
    """Un jpath porte « $ », « [ » et « : » : non échappé, il changerait la structure."""
    tricky = replace(DOC, keys=('$["mon:champ"]',), indexables=())

    assert read_storage(storage_text(tricky)) == tricky


def test_the_label_is_required() -> None:
    assert [(p.path, p.code) for p in form_problems(replace(DOC, label="  "))] == [
        ("libelle", "libelle_vide")
    ]


def test_an_empty_key_is_refused() -> None:
    assert [(p.path, p.code) for p in form_problems(replace(DOC, keys=()))] == [("cle", "cle_vide")]


def test_a_key_that_is_not_a_property_path_is_refused_with_its_rank() -> None:
    problems = form_problems(replace(DOC, keys=("$.l[*]", "$.a[2]")))

    assert [(p.path, p.code) for p in problems] == [
        ("cle[0]", "chemin_de_propriete_attendu"),
        ("cle[1]", "chemin_de_propriete_attendu"),
    ]


def test_the_same_key_twice_is_refused() -> None:
    problems = form_problems(replace(DOC, keys=("$.Id", "$.Id")))

    assert ("cle", "cle_doublee") in [(p.path, p.code) for p in problems]


def test_a_doubled_name_and_a_doubled_jpath_are_distinct_refusals() -> None:
    same_name = form_problems(
        replace(DOC, indexables=(Indexable("ville", "$.a"), Indexable("ville", "$.b")))
    )
    same_jpath = form_problems(
        replace(DOC, indexables=(Indexable("ville", "$.a"), Indexable("autre", "$.a")))
    )

    assert {(p.path, p.code) for p in same_name} == {
        ("indexables[0].nom", "nom_double"),
        ("indexables[1].nom", "nom_double"),
    }
    assert {(p.path, p.code) for p in same_jpath} == {
        ("indexables[0].jpath", "jpath_double"),
        ("indexables[1].jpath", "jpath_double"),
    }


def test_form_problems_are_all_reported() -> None:
    bad = StorageDoc("Sites!", "", "site", (), (Indexable("Nom!", "$.a"),))

    assert {(p.path, p.code) for p in form_problems(bad)} == {
        ("nom", "nom_invalide"),
        ("libelle", "libelle_vide"),
        ("modele", "modele_invalide"),
        ("cle", "cle_vide"),
        ("indexables[0].nom", "nom_invalide"),
    }


def test_only_the_storage_files_are_listed() -> None:
    paths = ["storages/sites.yaml", "storages/.gitkeep", "sources/crm.yaml", "storages/a/b.yaml"]

    assert names_in(paths) == ["sites"]
