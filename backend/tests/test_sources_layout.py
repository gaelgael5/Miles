from __future__ import annotations

from dataclasses import replace

import pytest

from miles.sources.layout import (
    Entry,
    EntryModes,
    SourceDoc,
    form_problems,
    read_source,
    source_text,
)

WEB = Entry(
    "web",
    "pudo/import-crm",
    "crm-vers-site",
    EntryModes(element=True, batch=True, file=True),
    "$.sites[*]",
    False,
    1,
)
# Refondue le 25/10/2026 : une source dit OÙ ça va, et porte ses entrées.
DOC = SourceDoc("crm", "CRM", "sites", (WEB,))


def test_declaration_is_written_and_reads_back_unchanged() -> None:
    text = source_text(DOC)

    assert read_source(text) == DOC
    assert source_text(DOC) == text


def test_a_source_without_any_entry_is_written_and_reads_back() -> None:
    """Le libellé, le slug et la donnée cible suffisent à enregistrer (Gael, 25/10/2026)."""
    bare = replace(DOC, entries=())

    assert read_source(source_text(bare)) == bare
    assert form_problems(bare) == []


@pytest.mark.parametrize(
    "text",
    [
        None,
        "- a\n",
        'nom: "x"\ninconnue: 1\n',
        'nom: "x"\nlibelle: 3\n',
        "nom: [\n",
        'nom: "x"\nlibelle: "X"\nstorage: "s"\nentrees: 3\n',
    ],
    ids=["absente", "liste", "cle-inconnue", "type", "illisible", "entrees-pas-liste"],
)
def test_malformed_declaration_is_unreadable(text: str | None) -> None:
    assert read_source(text) is None


def test_an_entry_with_an_unknown_key_is_unreadable() -> None:
    """On ne devine pas ce qu'une clé inconnue voulait dire dans une entrée."""
    text = (
        'nom: "crm"\nlibelle: "CRM"\nstorage: "sites"\nentrees:\n'
        '  - type: "web"\n    modele_source: "a/b"\n    chaine: "c"\n'
        '    decoupage: ""\n    modes:\n      element: true\n    surprise: 1\n'
    )

    assert read_source(text) is None


def test_a_source_of_the_old_shape_is_not_taken_up_in_silence() -> None:
    ancienne = (
        'nom: "crm"\nlibelle: "CRM"\nstorage: "sites"\nmodele_source: "a/b"\n'
        'decoupage: "$.x[*]"\nchaine: "c"\nmode_gros_fichier: true\n'
    )

    assert read_source(ancienne) is None


def test_the_target_data_is_required_and_never_guessed() -> None:
    assert [(p.path, p.code) for p in form_problems(replace(DOC, storage="  "))] == [
        ("storage", "storage_absent")
    ]


def test_an_entry_must_expose_at_least_one_method() -> None:
    """Sans mode coché, l'entrée n'expose rien : elle ne peut rien recevoir."""
    mute = replace(DOC, entries=(replace(WEB, modes=EntryModes(False, False, False)),))

    assert ("entrees[0].modes", "aucun_mode") in [(p.path, p.code) for p in form_problems(mute)]


def test_the_split_is_required_by_the_file_mode_and_by_it_alone() -> None:
    only_file = replace(WEB, modes=EntryModes(False, False, True), split="")
    no_file = replace(WEB, modes=EntryModes(True, True, False), split="")

    assert [(p.path, p.code) for p in form_problems(replace(DOC, entries=(only_file,)))] == [
        ("entrees[0].decoupage", "decoupage_absent")
    ]
    assert form_problems(replace(DOC, entries=(no_file,))) == []


@pytest.mark.parametrize(
    ("split", "detail"),
    [
        ("$.sites[?(@.actif == true)]", "un filtre exige l'item entier avant de le garder"),
        ("$..sites[*]", "descente « .. » non bornée"),
        ("$.sites[*].lignes[*]", "le joker doit terminer le chemin"),
        ("$.sites", "le chemin doit finir par [*]"),
    ],
    ids=["filtre", "descente", "joker-au-milieu", "pas-de-tableau"],
)
def test_a_split_that_cannot_be_read_as_a_stream_is_refused_with_its_reason(
    split: str, detail: str
) -> None:
    broken = replace(DOC, entries=(replace(WEB, split=split),))

    assert [(p.path, p.code, p.detail) for p in form_problems(broken)] == [
        ("entrees[0].decoupage", "non_streamable", detail)
    ]


def test_a_split_outside_the_file_mode_is_still_checked_when_it_is_there() -> None:
    """Admis vide, mais pas faux : un chemin écrit puis le mode décoché reste à corriger."""
    kept = replace(WEB, modes=EntryModes(True, False, False), split="$..sites[*]")

    assert [(p.path, p.code) for p in form_problems(replace(DOC, entries=(kept,)))] == [
        ("entrees[0].decoupage", "non_streamable")
    ]


def test_an_unknown_entry_type_is_refused_rather_than_ignored() -> None:
    other = replace(DOC, entries=(replace(WEB, kind="carrier-pigeon"),))

    assert [(p.path, p.code, p.detail) for p in form_problems(other)] == [
        ("entrees[0].type", "type_inconnu", "carrier-pigeon")
    ]


def test_each_entry_is_reported_under_its_own_rank() -> None:
    first = replace(WEB, source_model="pas un modele")
    second = replace(WEB, chain="  ")

    problems = form_problems(replace(DOC, entries=(first, second)))

    assert {(p.path, p.code) for p in problems} == {
        ("entrees[0].modele_source", "modele_invalide"),
        ("entrees[1].chaine", "chaine_absente"),
    }


def test_the_write_batch_says_how_often_one_writes_not_when_one_commits() -> None:
    """Gael, 25/10/2026 : « un nombre de lectures consécutives avant enregistrement ».

    Indépendant de la transaction unifiée : écrire par lots de 500 dans une transaction
    unique est une combinaison valide, et c'est même le cas d'usage d'un gros fichier.
    """
    both = replace(DOC, entries=(replace(WEB, write_batch=500, unified_transaction=True),))

    assert form_problems(both) == []
    assert read_source(source_text(both)) == both


def test_a_write_batch_below_one_would_never_write(write: int = 0) -> None:
    broken = replace(DOC, entries=(replace(WEB, write_batch=write),))

    assert [(p.path, p.code, p.detail) for p in form_problems(broken)] == [
        ("entrees[0].lot_ecriture", "lot_trop_petit", "0")
    ]


def test_an_absent_write_batch_falls_back_on_writing_each_read() -> None:
    """1 par défaut : on écrit ce qu'on vient de lire, le comportement le plus sûr."""
    text = (
        'nom: "crm"\nlibelle: "CRM"\nstorage: "sites"\nentrees:\n'
        '  - type: "web"\n    modele_source: "a/b"\n    chaine: "c"\n'
        "    modes:\n      element: true\n"
    )

    doc = read_source(text)

    assert doc is not None and doc.entries[0].write_batch == 1


def test_a_write_batch_that_is_not_a_whole_number_is_unreadable() -> None:
    # `True` est un `int` en Python : la garde le refuse explicitement.
    for value in ('"500"', "true", "1.5"):
        text = (
            'nom: "crm"\nlibelle: "CRM"\nstorage: "sites"\nentrees:\n'
            '  - type: "web"\n    modele_source: "a/b"\n    chaine: "c"\n'
            '    decoupage: ""\n'
            f"    modes:\n      element: true\n    lot_ecriture: {value}\n"
        )
        assert read_source(text) is None, value


def test_form_problems_are_all_reported() -> None:
    bad = SourceDoc("CRM!", "", "Pas Un Nom", ())

    assert {(p.path, p.code) for p in form_problems(bad)} == {
        ("nom", "nom_invalide"),
        ("libelle", "libelle_vide"),
        ("storage", "nom_invalide"),
    }
