"""Équivalence des deux lecteurs YAML, et refus inchangés (enabler 1af50397).

Le lecteur de production est celui de libyaml ; le lecteur pur Python reste le repli
quand libyaml manque. Un repli plus strict ou plus laxiste serait pire que l'absence de
gain : ce qui est admis, refusé, et la position rendue à l'éditeur se comparent ici
document par document, plutôt que de se déduire de la documentation de PyYAML.
"""

from __future__ import annotations

import pytest
import yaml

from miles_socle.parametrage.yaml_read import (
    LOADER,
    MAX_TEXT_BYTES,
    PURE_LOADER,
    ParametrageSyntaxError,
    load_yaml,
)

LECTEURS = [pytest.param(LOADER, id="libyaml"), pytest.param(PURE_LOADER, id="pur-python")]

# Les formes que portent les documents de paramétrage réels : arbres imbriqués, listes,
# scalaires multilignes, ancres, nombres, dates, nuls, guillemets, unicode. C'est le
# corpus de la comparaison mécanique entre les deux lecteurs (critère 8).
CORPUS = {
    "arbre": (
        "scope: ams\nname: Colis\nproperties:\n  nom: {type: string}\n  poids:\n    type: number\n"
    ),
    "listes": "items:\n  - un\n  - deux\n  - sous:\n      - 1\n      - 2\n",
    "scalaires": (
        "entier: 12\nflottant: 1.5\nvrai: true\nfaux: false\n"
        "nul: null\ntilde: ~\ndate: 2026-11-15\n"
    ),
    "guillemets": 'simple: \'a: b\'\ndouble: "ligne\\nsuite"\nvide: ""\n',
    "multiligne": "litteral: |\n  une ligne\n  une autre\nreplie: >\n  mot\n  mot\n",
    "ancres": "base: &b {type: string}\nautre: *b\n",
    "unicode": 'cle: "éàç 🙂"\nautre: naïve\n',
    "crlf": 'cle: "éàç"\r\nautre: v\r\nliste:\r\n  - un\r\n',
    "cles_non_texte": "1: un\n2: deux\n2026-11-15: jour\nfaux: non\n",
    "vide": "",
    "commentaire": "# rien à lire\n",
    "profond": "a:\n  b:\n    c:\n      d:\n        e: fin\n",
    "vides_imbriques": "map: {}\nliste: []\n",
}

# Trois familles d'erreur distinctes : les marques de position des deux lecteurs peuvent
# coïncider sur l'une et diverger sur l'autre.
INVALIDES = {
    "indentation": "a: 1\n  b: 2\n",
    "guillemet-non-ferme": 'a: "pas fermé\n',
    "tabulation": "a:\n\t- 1\n",
    "crochet-non-ferme": "a: [1, 2\n",
    "ancre-absente": "a: *manque\n",
}


@pytest.mark.parametrize("loader", LECTEURS)
@pytest.mark.parametrize("nom", sorted(CORPUS))
def test_both_readers_build_the_same_tree_for_every_document_of_the_corpus(
    nom: str, loader: type
) -> None:
    assert load_yaml(CORPUS[nom], loader=loader) == load_yaml(CORPUS[nom], loader=PURE_LOADER)


@pytest.mark.parametrize("loader", LECTEURS)
def test_a_duplicate_key_is_refused_by_both_readers(loader: type) -> None:
    with pytest.raises(ParametrageSyntaxError) as refus:
        load_yaml("a: 1\nb: 2\na: 3\n", loader=loader)

    assert "clé en double : a" in str(refus.value)
    assert (refus.value.line, refus.value.column) == (3, 1)


@pytest.mark.parametrize("loader", LECTEURS)
def test_a_duplicate_key_nested_in_a_mapping_is_refused_too(loader: type) -> None:
    with pytest.raises(ParametrageSyntaxError, match="clé en double : k"):
        load_yaml("x:\n  k: 1\n  k: 2\n", loader=loader)


@pytest.mark.parametrize("loader", LECTEURS)
def test_the_strictness_comes_from_the_constructor_and_not_from_the_reader(loader: type) -> None:
    """Le test de clé en double rougirait si le constructeur strict était retiré.

    Preuve par injection : le lecteur NU des deux côtés garde la dernière clé en silence,
    et c'est exactement le défaut que le constructeur enregistré vient supprimer.
    """
    nu = loader.__bases__[0]

    assert yaml.load("a: 1\na: 2\n", Loader=nu) == {"a": 2}  # noqa: S506  # lecteur nu, du test


@pytest.mark.parametrize("nom", sorted(INVALIDES))
def test_an_invalid_document_is_refused_at_the_same_position_by_both_readers(nom: str) -> None:
    """La position est ce dont se sert l'éditeur pour amener la personne sur sa faute.

    Seul le LIBELLÉ de PyYAML diffère entre les deux lecteurs (« mapping values are not
    allowed here » contre « … in this context ») : il n'est pas comparé, la position
    l'est.
    """
    with pytest.raises(ParametrageSyntaxError) as rapide:
        load_yaml(INVALIDES[nom], loader=LOADER)
    with pytest.raises(ParametrageSyntaxError) as pur:
        load_yaml(INVALIDES[nom], loader=PURE_LOADER)

    assert (rapide.value.line, rapide.value.column) == (pur.value.line, pur.value.column)
    # Une position toujours rendue, et numérotée comme dans un éditeur (à partir de 1).
    assert rapide.value.line is not None and rapide.value.line >= 1
    assert rapide.value.column is not None and rapide.value.column >= 1


@pytest.mark.parametrize("loader", LECTEURS)
def test_an_empty_document_and_a_comment_only_document_read_as_nothing(loader: type) -> None:
    assert load_yaml("", loader=loader) is None
    assert load_yaml("# rien\n", loader=loader) is None


@pytest.mark.parametrize("loader", LECTEURS)
def test_a_document_over_the_size_bound_is_refused_before_any_parsing(loader: type) -> None:
    trop = "a: " + "x" * MAX_TEXT_BYTES + '\nb: "jamais analysé\n'

    with pytest.raises(ParametrageSyntaxError) as refus:
        load_yaml(trop, loader=loader)

    # Le refus de taille gagne sur l'erreur de syntaxe : rien n'a été analysé.
    assert str(refus.value) == "document trop volumineux"
    assert (refus.value.line, refus.value.column) == (None, None)


@pytest.mark.parametrize("loader", LECTEURS)
def test_a_document_just_under_the_bound_is_read(loader: type) -> None:
    juste = "a: " + "x" * (MAX_TEXT_BYTES - 10)

    assert load_yaml(juste, loader=loader) == {"a": "x" * (MAX_TEXT_BYTES - 10)}


@pytest.mark.parametrize("loader", LECTEURS)
def test_accents_emoji_and_windows_line_endings_are_read_identically(loader: type) -> None:
    lu = load_yaml('cle: "éàç 🙂"\r\nautre: naïve\r\n', loader=loader)

    assert lu == {"cle": "éàç 🙂", "autre": "naïve"}


@pytest.mark.skipif(not hasattr(yaml, "CSafeLoader"), reason="libyaml absent de l'environnement")
def test_the_chosen_reader_is_the_libyaml_one_when_it_is_available() -> None:
    """Sans quoi le gain mesuré (8,0 fois) ne serait pas celui du service déployé."""
    assert LOADER.__bases__ == (yaml.CSafeLoader,)
    assert PURE_LOADER.__bases__ == (yaml.SafeLoader,)
