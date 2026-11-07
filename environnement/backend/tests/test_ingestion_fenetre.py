"""Les gardes de la lecture par FENÊTRE GLISSANTE, que la lecture jeton par jeton n'avait pas.

Un lecteur qui analyse une valeur à la fois dans un tampon borné se trompe à trois
endroits, et chacun se trompe EN SILENCE — ce qui est pire que lentement :

1. une valeur à cheval sur deux fenêtres ;
2. `raw_decode` acceptant un PRÉFIXE valide : `123456789` coupé en `123` est un nombre ;
3. l'analyseur C ne bornant pas la profondeur, là où le dépôt promet un refus rendu.

Les tests de `test_ingestion_stream.py` restent la spécification du comportement visible,
et ils passent sans modification. Ceux-ci éprouvent le mécanisme qui le rend.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from environnement.ingestion import jsonwindow
from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    DOCUMENT_TOO_DEEP,
    MAX_DEPTH,
    METADATA_TOO_LARGE,
    DocumentUnreadable,
)
from environnement.ingestion.stream import file_iter_items, file_read_metadata

# Des fenêtres volontairement absurdes : plus petites qu'un item, plus petites qu'une clé.
# C'est là que le rechargement se trompe, pas à 128 Kio.
FENETRES = [8, 17, 64, 129, 1024, 1 << 20]


def _write(tmp_path: Path, content: str) -> Path:
    document = tmp_path / "depot.json"
    document.write_text(content, encoding="utf-8")
    return document


def _document(tmp_path: Path, value: Any) -> Path:
    return _write(tmp_path, json.dumps(value))


@pytest.mark.parametrize("fenetre", FENETRES)
def test_the_items_read_do_not_depend_on_the_window_size(tmp_path: Path, fenetre: int) -> None:
    """La garde centrale : le résultat est le même à 8 octets de fenêtre qu'à 1 Mio."""
    items = [{"code": f"FR-{rang:05d}", "nom": "Épicerie du Pont", "n": rang} for rang in range(40)]
    document = _document(tmp_path, {"entete": {"total": 40}, "root": items})

    assert list(file_iter_items(document, ("root",), window_size=fenetre)) == items


@pytest.mark.parametrize("fenetre", FENETRES)
def test_the_metadata_do_not_depend_on_the_window_size(tmp_path: Path, fenetre: int) -> None:
    document = _document(
        tmp_path, {"genere_le": "2026-11-07", "root": [{"a": 1}] * 30, "total": 30}
    )

    assert file_read_metadata(document, ("root",), 1_000, window_size=fenetre) == {
        "genere_le": "2026-11-07",
        "total": 30,
    }


@pytest.mark.parametrize("fenetre", [18, 19, 20, 21, 22, 23, 24, 25, 26])
def test_a_number_cut_by_the_window_is_never_read_truncated(tmp_path: Path, fenetre: int) -> None:
    """Le piège de `raw_decode` : un préfixe de nombre est un nombre VALIDE.

    Sans la garde de troncature, ce test rend `[1234, 9876, 4]` au lieu des valeurs
    entières — et rien ne le signale. Les fenêtres encadrent la coupure de chaque nombre.
    """
    document = _write(tmp_path, '{"root": [123456789, 987654321, 42]}')

    assert list(file_iter_items(document, ("root",), window_size=fenetre)) == [
        123456789,
        987654321,
        42,
    ]


@pytest.mark.parametrize("litteral", [True, False, None], ids=["true", "false", "null"])
def test_a_literal_cut_by_the_window_is_never_read_truncated(tmp_path: Path, litteral: Any) -> None:
    """`true` coupé en `tru` échoue, mais la garde doit tenir aussi pour les littéraux."""
    document = _document(tmp_path, {"root": [litteral, litteral]})

    for fenetre in range(10, 24):
        assert list(file_iter_items(document, ("root",), window_size=fenetre)) == [
            litteral,
            litteral,
        ]


def test_an_item_larger_than_the_window_is_read_whole(tmp_path: Path) -> None:
    """La fenêtre grandit pour l'item en cours : elle borne le document, pas un item."""
    item = {"corps": "x" * 20_000, "n": 1}
    document = _document(tmp_path, {"root": [item, item]})

    assert list(file_iter_items(document, ("root",), window_size=64)) == [item, item]


def test_a_truncated_number_at_the_end_of_the_document_is_refused(tmp_path: Path) -> None:
    """Le cas que la garde de fin de document attrape : plus rien à lire, et un nombre
    qui pourrait être amputé. Le refuser, plutôt que rendre une valeur plausible."""
    document = _write(tmp_path, '{"root": [1, 23456')

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",)))

    assert refus.value.code == DOCUMENT_INVALID


def test_a_key_placed_before_the_array_is_traversed_without_being_built(
    tmp_path: Path,
) -> None:
    """Rien ne garantit que ce qui PRÉCÈDE le tableau visé soit petit.

    Mesuré en mémoire résidente : une propriété de 40 Mio placée avant le découpage doit
    être traversée, jamais construite. Sans `skip_value`, la lecture la décoderait pour
    l'atteindre et le mode fichier ne tiendrait plus sa promesse sur ce document-là.
    """
    document = tmp_path / "gros_entete.json"
    with document.open("w", encoding="utf-8") as handle:
        handle.write('{"avant": "')
        for _ in range(8):
            handle.write("x" * (1 << 20))
        handle.write('", "root": [{"a": 1}, {"a": 2}]}')

    tracemalloc.start()
    lus = list(file_iter_items(document, ("root",)))
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert lus == [{"a": 1}, {"a": 2}]
    assert document.stat().st_size > 8 * (1 << 20)
    # Le pic d'ALLOCATION, et non `ru_maxrss` : celui-ci est un maximum monotone du
    # processus, qu'un test précédent a déjà pu élever — l'assertion passerait alors à
    # vide, sans rien prouver. Un mégaoctet laisse la place à la fenêtre et refuse les
    # huit de la propriété traversée.
    assert pic < (1 << 20)


def test_the_omitted_array_is_not_held_in_memory_either(tmp_path: Path) -> None:
    """La passe des métadonnées DRAINE le tableau des items : elle n'en garde rien.

    C'est la mesure qui a imposé de réécrire cette passe aussi — elle traversait tout le
    document jeton par jeton. Qu'elle soit rapide ne suffit pas : elle doit rester bornée.
    """
    item = json.dumps({"cle": "y" * 500, "n": 1})
    document = tmp_path / "gros.json"
    with document.open("w", encoding="utf-8") as handle:
        handle.write('{"root": [')
        handle.write(",".join([item] * 20_000))
        handle.write('], "total": 20000}')
    taille = document.stat().st_size

    tracemalloc.start()
    lu = file_read_metadata(document, ("root",), 1_000)
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert lu == {"total": 20_000}
    assert taille > 10_000_000
    assert pic < taille // 10


def test_a_wide_item_is_read_although_it_has_many_opening_brackets(tmp_path: Path) -> None:
    """Le filtre bon marché de profondeur compte les crochets OUVRANTS, pas la profondeur.

    Un item LARGE en porte beaucoup sans être profond. Le filtre doit donc déclencher le
    parcours — et le parcours doit l'ACCEPTER. Sans ce test, confondre « beaucoup de
    conteneurs » avec « profondément imbriqué » refuserait des items parfaitement légitimes,
    et le défaut n'apparaîtrait que sur les documents les plus riches.
    """
    item = {f"p{rang}": {"v": rang} for rang in range(MAX_DEPTH * 2)}
    document = _document(tmp_path, {"root": [item]})

    assert json.dumps(item).count("{") > MAX_DEPTH
    assert list(file_iter_items(document, ("root",))) == [item]


def test_a_deep_item_is_refused_whatever_the_window_size(tmp_path: Path) -> None:
    profond: Any = 1
    for _ in range(MAX_DEPTH + 5):
        profond = {"n": profond}
    document = _document(tmp_path, {"root": [profond]})

    for fenetre in (64, 4096, 1 << 20):
        with pytest.raises(DocumentUnreadable) as refus:
            list(file_iter_items(document, ("root",), window_size=fenetre))
        assert refus.value.code == DOCUMENT_TOO_DEEP


def test_a_document_that_is_not_utf8_is_refused_as_invalid(tmp_path: Path) -> None:
    """Sans ce refus, l'erreur remonterait brute du codec et ne dirait pas que c'est le
    DÉPÔT qui est en cause."""
    document = tmp_path / "latin.json"
    document.write_bytes(b'{"root": [{"nom": "\xe9picerie"}]}')

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",)))

    assert refus.value.code == DOCUMENT_INVALID


def test_metadata_whose_text_is_beyond_the_cap_are_refused_before_being_built(
    tmp_path: Path,
) -> None:
    """Le budget se compte en nœuds, mais une valeur s'analyse d'un seul appel.

    Le plafond de texte est ce qui rend la borne de MÉMOIRE avant l'analyse : sans lui, un
    en-tête démesuré serait construit en entier pour être refusé juste après, ce qui est
    exactement ce que le mode fichier promet d'éviter.
    """
    document = _document(tmp_path, {"root": [], "entete": "z" * 10_000})

    with pytest.raises(DocumentUnreadable) as refus:
        file_read_metadata(document, ("root",), 10)

    assert refus.value.code == METADATA_TOO_LARGE


def test_a_single_value_beyond_the_hard_cap_is_refused_rather_than_grown_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La fenêtre grandit pour l'item en cours : il faut bien qu'elle s'arrête.

    Éprouvé avec le plafond rabaissé plutôt qu'avec un fichier de 64 Mio : ce qui est
    testé est l'ARRÊT de la croissance, pas la valeur de la borne.
    """
    monkeypatch.setattr(jsonwindow, "VALUE_MAX", 4096)
    document = _document(tmp_path, {"root": [{"corps": "w" * 200_000}]})

    with pytest.raises(DocumentUnreadable) as refus:
        list(file_iter_items(document, ("root",), window_size=1024))

    assert refus.value.code == DOCUMENT_INVALID
    assert refus.value.detail is not None and "4096" in refus.value.detail
