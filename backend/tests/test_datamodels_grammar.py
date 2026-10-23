from __future__ import annotations

import pytest

from miles.datamodels.grammar import (
    MAX_LIST_DEPTH,
    ModelGrammarError,
    ModelSyntaxError,
    Problem,
    parse_model,
    references_of,
)

# Exemple du ticket 266f5ed8, repris tel quel.
COLIS = """nom: colis
version: 2
description: Colis tel que le terminal le manipule
proprietes:
  reference:
    type: chaine
    obligatoire: true
  statut:
    type: enumeration
    valeurs: [attendu, recu, remis, retourne]
    obligatoire: true
  destinataire:
    type: objet
    modele: personne
  arrive_le:
    type: horodatage
"""


def _problems(text: str) -> list[Problem]:
    with pytest.raises(ModelGrammarError) as caught:
        parse_model(text)
    return caught.value.problems


def _with(properties: str) -> str:
    return f"nom: m\nversion: 1\nproprietes:\n{properties}"


def test_ticket_example_is_accepted_with_its_reference() -> None:
    model = parse_model(COLIS)

    assert (model.name, model.version) == ("colis", 2)
    assert model.references == (("proprietes.destinataire.modele", "personne"),)


@pytest.mark.parametrize("kind", ["chaine", "entier", "decimal", "booleen", "date", "horodatage"])
def test_every_scalar_type_of_the_first_batch_is_accepted(kind: str) -> None:
    assert parse_model(_with(f"  p:\n    type: {kind}\n")).name == "m"


def test_invalid_yaml_is_refused_with_its_line_and_column() -> None:
    with pytest.raises(ModelSyntaxError) as caught:
        parse_model("nom: colis\nproprietes:\n  a: [chaine\n")

    assert caught.value.line is not None and caught.value.line >= 3
    assert caught.value.column is not None


def test_duplicate_key_is_refused_instead_of_keeping_the_last() -> None:
    with pytest.raises(ModelSyntaxError) as caught:
        parse_model(_with("  p:\n    type: chaine\n  p:\n    type: entier\n"))

    assert "clé en double : p" in caught.value.message
    assert caught.value.line == 6


def test_every_problem_is_reported_not_only_the_first() -> None:
    text = """nom: Colis
version: 0
couleur: rouge
proprietes:
  a:
    obligatoire: true
  b:
    type: texte
  c:
    type: enumeration
  d:
    type: chaine
    valeurs: [x]
"""

    assert _problems(text) == [
        Problem("couleur", "cle_inconnue"),
        Problem("nom", "nom_invalide"),
        Problem("version", "version_invalide"),
        Problem("proprietes.a.type", "obligatoire"),
        Problem("proprietes.b.type", "type_inconnu", "texte"),
        Problem("proprietes.c.valeurs", "obligatoire"),
        Problem("proprietes.d.valeurs", "cle_hors_type", "enumeration"),
    ]


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        # YAML 1.1 lit on/off et yes/no comme des booléens : on le nomme au lieu de convertir.
        ("  p:\n    type: enumeration\n    valeurs: [a, on]\n", "valeurs_textuelles_attendues"),
        ("  p:\n    type: enumeration\n    valeurs: [a, a]\n", "valeurs_en_double"),
        ("  p:\n    type: enumeration\n    valeurs: []\n", "liste_non_vide_attendue"),
        ("  p:\n    type: objet\n", "obligatoire"),
        ("  p:\n    type: chaine\n    obligatoire: oui\n", "booleen_attendu"),
        ("  P:\n    type: chaine\n", "nom_de_propriete_invalide"),
    ],
    ids=["on-off", "doublon", "vide", "objet-sans-modele", "obligatoire-non-booleen", "nom"],
)
def test_property_mistakes_are_named(properties: str, expected: str) -> None:
    assert [p.code for p in _problems(_with(properties))] == [expected]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("- a\n- b\n", "document_non_objet"),
        ("nom: m\nversion: 1\nproprietes: []\n", "objet_attendu"),
        ("nom: m\nversion: true\nproprietes:\n  p:\n    type: chaine\n", "version_invalide"),
        ("version: 1\nproprietes:\n  p:\n    type: chaine\n", "obligatoire"),
    ],
    ids=["liste", "proprietes-en-liste", "version-booleenne", "sans-nom"],
)
def test_document_mistakes_are_named(text: str, code: str) -> None:
    assert [p.code for p in _problems(text)] == [code]


def test_a_model_without_property_is_an_admitted_draft() -> None:
    # Brouillon (Gael, 23/10/2026) : admis à l'écriture, refusé dans une version.
    draft = parse_model("nom: m\nversion: 1\nproprietes: {}\n")
    full = parse_model(_with("  p:\n    type: chaine\n"))

    assert (draft.name, draft.empty) == ("m", True)
    assert full.empty is False


def _nested(depth: int) -> str:
    """Propriété liste imbriquée `depth` fois, d'éléments chaîne au fond."""
    lines, indent = ["  p:"], "    "
    for _ in range(depth):
        lines += [f"{indent}type: liste", f"{indent}elements:"]
        indent += "  "
    lines.append(f"{indent}type: chaine")
    return _with("\n".join(lines) + "\n")


@pytest.mark.parametrize("depth", [0, 1, MAX_LIST_DEPTH])
def test_lists_are_accepted_up_to_the_maximum_depth(depth: int) -> None:
    assert parse_model(_nested(depth)).name == "m"


def test_list_nested_beyond_the_maximum_is_refused_with_the_limit() -> None:
    [problem] = _problems(_nested(MAX_LIST_DEPTH + 1))

    assert (problem.code, problem.detail) == ("imbrication_trop_profonde", str(MAX_LIST_DEPTH))


def test_list_needs_its_elements_and_refers_through_them() -> None:
    objects = parse_model(
        _with("  p:\n    type: liste\n    elements:\n      type: objet\n      modele: colis\n")
    )

    assert objects.references == (("proprietes.p.elements.modele", "colis"),)
    assert [p.code for p in _problems(_with("  p:\n    type: liste\n"))] == ["obligatoire"]
    # `obligatoire` vaut pour la propriété, pas pour les éléments d'une liste.
    inner = _with(
        "  p:\n    type: liste\n    elements:\n      type: chaine\n      obligatoire: true\n"
    )
    assert _problems(inner) == [Problem("proprietes.p.elements.obligatoire", "cle_inconnue")]


def test_references_are_found_even_in_a_document_that_no_longer_conforms() -> None:
    retouched = "nom: x\nproprietes:\n  a:\n    type: objet\n    modele: colis\n    en_trop: 1\n"

    assert references_of(retouched) == {"colis"}
    assert references_of("pas: [du yaml") == set()
