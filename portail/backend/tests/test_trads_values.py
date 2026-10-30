from __future__ import annotations

import pytest
import yaml

from miles.workshop.trads import TradsFileError
from miles.workshop.trads_values import (
    MARKS,
    ReorderingError,
    SlugError,
    TradsInputError,
    checked_slug,
    checked_value,
    values_of,
    values_text,
)

# Valeurs réellement difficiles : chacune a cassé un outil de traduction quelque part.
DIFFICILES = {
    "simple": "Bonjour",
    "multi": "Ligne 1\nLigne 2\n",
    "multi_sans_fin": "Ligne 1\nLigne 2",
    "espace_fin_ligne": "Ligne 1 \nLigne 2",
    "guillemets": "Il a dit \"oui\" et 'non'",
    "arabe": "مرحبا بالعالم",
    "hebreu": "שלום עולם",
    "thai": "สวัสดีครับ",
    "devanagari": "नमस्ते",
    "ideogrammes": "你好世界",
    "marque_rlm": "Nom‏suite",
    "accolades": "Bonjour {nom}",
    "yaml_piege": "oui: non",
    "tabulation": "a\tb",
    "espaces_bordants": "  bordé  ",
    "deux_points": "Heure: 12:30",
    "tiret": "- pas une liste",
    "nombre": "42",
    "booleen": "true",
    "espace_seul": " ",
    "mixte": "Facture n° 12 — فاتورة",
}


@pytest.mark.parametrize("slug", ["titre", "a", "ecran_accueil_bouton", "lot-2", "x9", "x" * 120])
def test_checked_slug_accepts_a_key_slug(slug: str) -> None:
    assert checked_slug(slug) == slug


@pytest.mark.parametrize(
    "hostile",
    ["Titre", "mon titre", "été", "a.b", "a/b", "..", "", "-titre", "_titre", "x" * 121, "ok\n"],
)
def test_checked_slug_refuses_the_rest(hostile: str) -> None:
    """Pas de point : il suggérerait une hiérarchie, et la forme des références n'est pas
    tranchée. Pas de séparateur de chemin non plus."""
    with pytest.raises(SlugError):
        checked_slug(hostile)


# --- Critère 13 : l'aller-retour disque conserve la valeur à l'identique ---


def test_every_difficult_value_survives_a_round_trip_unchanged() -> None:
    relu = values_of("p", values_text(DIFFICILES))

    assert relu == DIFFICILES


def test_a_number_like_value_comes_back_as_text_not_as_a_number() -> None:
    """« 42 » est un libellé, pas un entier : le fichier le cite pour cette raison."""
    assert "'42'" in values_text({"n": "42"})
    assert values_of("p", values_text({"n": "42"}))["n"] == "42"


def test_the_file_stays_readable_by_a_human() -> None:
    text = values_text({"titre": "Bonjour", "arabe": "مرحبا"})

    # Les glyphes restent lisibles — pas d'échappement \\uXXXX — et les clés sont triées.
    assert "مرحبا" in text
    assert text.index("arabe") < text.index("titre")


def test_multiline_values_use_the_literal_style_so_the_diff_reads() -> None:
    text = values_text({"corps": "Ligne 1\nLigne 2\n"})

    assert "corps: |" in text
    assert values_of("p", text)["corps"] == "Ligne 1\nLigne 2\n"


def test_values_text_is_stable_so_a_second_save_shows_no_diff() -> None:
    # Dans l'ordre inverse du tri : deux saisies qui touchent les mêmes valeurs dans un
    # ordre différent doivent produire le MÊME fichier, sans quoi le diff ment.
    once = values_text(DIFFICILES)
    inverse = values_text(dict(reversed(list(DIFFICILES.items()))))

    assert values_text(values_of("p", once)) == once
    assert inverse == once


def test_adding_a_key_only_adds_a_line_to_the_file() -> None:
    """Trié par slug : ajouter une clé ne doit pas réécrire le fichier entier.

    Les clés sont passées dans le DÉSORDRE exprès : un jeu d'essai déjà trié resterait
    vert même si le tri disparaissait, `dict` conservant l'ordre d'insertion.
    """
    before = values_text({"gamma": "C", "alpha": "A"}).splitlines()
    after = values_text({"gamma": "C", "beta": "B", "alpha": "A"}).splitlines()

    assert before == ["alpha: A", "gamma: C"]
    assert [line for line in after if line not in before] == ["beta: B"]


def test_an_empty_set_of_values_writes_an_explicit_empty_mapping() -> None:
    """Un fichier vide ne dirait pas « cette culture est connue et n'a rien »."""
    assert values_text({}) == "{}\n"
    assert values_of("p", "{}\n") == {}


def test_values_of_an_absent_or_empty_file_has_no_value() -> None:
    assert values_of("p", None) == {}
    assert values_of("p", "") == {}


def test_values_of_a_hand_written_file_without_quotes_still_reads() -> None:
    """Un fichier écrit à la main se lit : la valeur est du texte, quoi que YAML en pense."""
    assert values_of("p", "n: 42\nb: true\nvide:\n") == {"n": "42", "b": "True", "vide": ""}


def test_values_of_unreadable_yaml_names_the_file() -> None:
    with pytest.raises(TradsFileError, match="illisible"):
        values_of("p", "titre: [non fermé\n")


def test_values_of_a_list_is_refused() -> None:
    with pytest.raises(TradsFileError, match="mappe"):
        values_of("p", "- titre\n")


# --- Critère 12 : les caractères qui réordonnent sont refusés et nommés ---


@pytest.mark.parametrize(
    ("char", "name"),
    [
        ("‪", "U+202A"),
        ("‫", "U+202B"),
        ("‬", "U+202C"),
        ("‭", "U+202D"),
        ("‮", "U+202E"),
        ("⁦", "U+2066"),
        ("⁧", "U+2067"),
        ("⁨", "U+2068"),
        ("⁩", "U+2069"),
    ],
)
def test_reordering_characters_are_refused_and_named(char: str, name: str) -> None:
    """Ils font qu'une chaîne s'affiche autrement qu'elle n'est écrite."""
    with pytest.raises(ReorderingError) as refus:
        checked_value(f"Bonjour{char}le monde")

    assert any(name in found for found in refus.value.found)


def test_several_reordering_characters_are_all_named_once() -> None:
    with pytest.raises(ReorderingError) as refus:
        checked_value("‮ a ‮ b ⁦ c")

    assert len(refus.value.found) == 2


@pytest.mark.parametrize("mark", sorted(MARKS))
def test_simple_direction_marks_are_accepted_unchanged(mark: str) -> None:
    """Elles ne donnent une direction qu'au caractère neutre voisin, sans rien retourner :
    un nom de marque latin au milieu d'une phrase arabe en a besoin."""
    value = f"Nom{mark}suite"

    assert checked_value(value) == value


def test_a_value_is_never_normalised() -> None:
    """Nettoyer les espaces changerait ce que quelqu'un a voulu écrire dans sa langue."""
    assert checked_value("  deux  espaces  ") == "  deux  espaces  "
    assert checked_value("fin\n") == "fin\n"


def test_an_overlong_value_is_refused() -> None:
    with pytest.raises(TradsInputError, match="trop longue"):
        checked_value("x" * 4001)


def test_a_refusal_never_carries_the_value_itself() -> None:
    """Le message part aux journaux : il ne doit pas y recopier ce que la personne a saisi."""
    with pytest.raises(ReorderingError) as refus:
        checked_value("secret métier ‮")

    assert "secret métier" not in str(refus.value)


def test_a_value_that_looks_like_yaml_structure_stays_a_string() -> None:
    """Une valeur qui ressemble à du YAML ne doit pas devenir une structure au relire."""
    piege = {"k": "{a: b}", "l": "[1, 2]", "m": "*ancre", "n": "&ancre x"}

    assert values_of("p", values_text(piege)) == piege
    assert isinstance(yaml.safe_load(values_text(piege))["k"], str)
