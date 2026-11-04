from __future__ import annotations

from dataclasses import replace

import pytest

from miles.storages.layout import (
    Index,
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
    (Index("par-ville", ("$.adresse.ville", "$.Name")),),
)


def test_declaration_is_written_and_reads_back_unchanged() -> None:
    text = storage_text(DOC)

    assert read_storage(text) == DOC
    assert storage_text(DOC) == text


def test_a_storage_without_any_index_round_trips() -> None:
    bare = replace(DOC, indexes=())

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
    tricky = replace(DOC, keys=('$["mon:champ"]',), indexes=())

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


def test_two_indexes_of_the_same_name_are_refused() -> None:
    doubled = form_problems(
        replace(DOC, indexes=(Index("ville", ("$.a",)), Index("ville", ("$.b",))))
    )

    assert {(p.path, p.code) for p in doubled} == {
        ("index[0].nom", "nom_double"),
        ("index[1].nom", "nom_double"),
    }


def test_an_index_carries_between_one_and_three_columns() -> None:
    """Gael, 24/10/2026 : autant d'index que nécessaire, trois colonnes au plus."""
    empty = form_problems(replace(DOC, indexes=(Index("vide", ()),)))
    three = form_problems(replace(DOC, indexes=(Index("trois", ("$.a", "$.b", "$.c")),)))
    four = form_problems(replace(DOC, indexes=(Index("quatre", ("$.a", "$.b", "$.c", "$.d")),)))

    assert [(p.path, p.code) for p in empty] == [("index[0].colonnes", "index_sans_colonne")]
    assert three == []
    assert [(p.path, p.code, p.detail) for p in four] == [
        ("index[0].colonnes", "trop_de_colonnes", "4")
    ]


def test_many_indexes_are_allowed() -> None:
    """« autant que nécessaire » : seul le nombre de COLONNES est plafonné."""
    many = tuple(Index(f"index-{n}", ("$.a",)) for n in range(12))

    assert form_problems(replace(DOC, indexes=many)) == []


def test_the_same_column_twice_in_one_index_is_refused() -> None:
    doubled = form_problems(replace(DOC, indexes=(Index("deux", ("$.a", "$.a")),)))

    assert {(p.path, p.code) for p in doubled} == {
        ("index[0].colonnes[0]", "colonne_doublee"),
        ("index[0].colonnes[1]", "colonne_doublee"),
    }


def test_the_same_column_in_two_different_indexes_is_fine() -> None:
    """Deux index composites peuvent partager une colonne : ils ne servent pas le même filtre."""
    shared = (Index("un", ("$.a", "$.b")), Index("deux", ("$.a", "$.c")))

    assert form_problems(replace(DOC, indexes=shared)) == []


def test_an_old_declaration_is_read_as_one_column_indexes() -> None:
    """Avant le 24/10/2026 un index couvrait une propriété : la conversion est exacte."""
    ancienne = (
        'nom: "sites"\nlibelle: "Sites"\nmodele: "pudo/site"\ncle:\n  - "$.Id"\n'
        'indexables:\n  - nom: "ville"\n    jpath: "$.adresse.ville"\n'
    )

    doc = read_storage(ancienne)

    assert doc is not None
    assert doc.indexes == (Index("ville", ("$.adresse.ville",)),)


def test_the_two_forms_at_once_are_refused_rather_than_arbitrated() -> None:
    both = (
        'nom: "sites"\nlibelle: "Sites"\nmodele: "pudo/site"\ncle:\n  - "$.Id"\n'
        "index: []\nindexables: []\n"
    )

    assert read_storage(both) is None


def test_form_problems_are_all_reported() -> None:
    bad = StorageDoc("Sites!", "", "site", (), (Index("Nom!", ("$.a",)),))

    assert {(p.path, p.code) for p in form_problems(bad)} == {
        ("nom", "nom_invalide"),
        ("libelle", "libelle_vide"),
        ("modele", "modele_invalide"),
        ("cle", "cle_vide"),
        ("index[0].nom", "nom_invalide"),
    }


def test_only_the_storage_files_are_listed() -> None:
    paths = ["storages/sites.yaml", "storages/.gitkeep", "sources/crm.yaml", "storages/a/b.yaml"]

    assert names_in(paths) == ["sites"]
