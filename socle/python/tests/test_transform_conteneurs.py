"""Ce que `$where` répond quand la comparaison porte sur un tableau ou un objet.

Jusqu'à urban-json 0.8.0, TOUT opérateur de comparaison rendait `false` dès qu'un côté
était un conteneur. Deux conséquences, toutes deux silencieuses : deux tableaux
identiques se disaient différents, et `a < b` comme `a >= b` étaient faux ENSEMBLE — ce
qui n'est pas une réponse possible. Depuis 0.9.0, l'égalité est STRUCTURELLE et l'ordre
est REFUSÉ.

Ce fichier tient le comportement du côté de Miles, parce que c'est Miles qui en porte la
conséquence visible : un `$where` qui ne filtrait rien se met à rendre des lignes, et une
comparaison d'ordre fait désormais ÉCHOUER l'étape — l'item est rejeté avec son motif
plutôt qu'écarté sans trace. Mesuré le 27/11/2026 à la montée 0.6.0 → 0.9.0.
"""

from __future__ import annotations

from typing import Any

import pytest

from miles_socle.transform.engine import EvaluationError, compile_template, evaluate

BUDGET = 100_000

# `tags` et `memes` portent les MÊMES éléments sur les lignes 1 et 3, dans un autre ordre
# sur la 2 : l'égalité structurelle doit retenir 1 et 3 et laisser la 2, ce qu'un test sur
# une seule ligne ne prouverait pas.
LIGNES: dict[str, Any] = {
    "l": [
        {"id": 1, "tags": ["a", "b"], "memes": ["a", "b"], "meta": {"x": 1}, "meta2": {"x": 1}},
        {"id": 2, "tags": ["a", "b"], "memes": ["b", "a"], "meta": {"x": 2}, "meta2": {"x": 1}},
        {"id": 3, "tags": [], "memes": [], "meta": {"x": 1}, "meta2": {"x": 1}},
    ]
}


def _boucle(predicat: str) -> str:
    return '{ "l": [ { "$source": $.l, "$where": ' + predicat + ', "id": $.id } ] }'


class TestLEgaliteDeDeuxConteneurs:
    def test_deux_tableaux_de_memes_elements_dans_le_meme_ordre_sont_egaux(self) -> None:
        rendu = evaluate(compile_template(_boucle("$.tags == $.memes")), LIGNES, BUDGET)

        assert [ligne["id"] for ligne in rendu["l"]] == [1, 3]

    def test_deux_objets_de_memes_clefs_et_memes_valeurs_sont_egaux(self) -> None:
        rendu = evaluate(compile_template(_boucle("$.meta == $.meta2")), LIGNES, BUDGET)

        assert [ligne["id"] for ligne in rendu["l"]] == [1, 3]

    def test_un_conteneur_compare_a_un_scalaire_reste_different(self) -> None:
        """Discriminant : l'égalité s'est élargie aux conteneurs, pas à n'importe quoi.

        Le côté GAUCHE décide de la règle appliquée, et c'est vrai des deux versions :
        `$.tags == $.id` est faux, quand `$.id == $.tags` échoue sur « valeur non
        convertible en nombre » — déjà le cas en 0.6.0, mesuré, et inchangé.
        """
        rendu = evaluate(compile_template(_boucle("$.tags == $.id")), LIGNES, BUDGET)

        assert rendu["l"] == []


class TestLOrdreEntreConteneurs:
    """Refusé, et le refus est NOMMÉ : c'est ce qui le distingue d'un filtre vide."""

    @pytest.mark.parametrize("operateur", ["<", "<=", ">", ">="])
    def test_comparer_l_ordre_de_deux_tableaux_fait_echouer_l_etape(self, operateur: str) -> None:
        modele = compile_template(_boucle(f"$.tags {operateur} $.memes"))

        with pytest.raises(EvaluationError) as leve:
            evaluate(modele, LIGNES, BUDGET)

        # Code générique `evaluation` : le moteur lève, Miles enveloppe — ce qui compte
        # est que le message nomme l'opérateur et le conteneur, pour que l'auteur du
        # template sache quoi corriger. Sans cela, le rejet d'ingestion dirait seulement
        # « transformation en échec ».
        assert leve.value.code == "evaluation"
        assert operateur in str(leve.value.message)
        assert "tableau" in str(leve.value.message)

    def test_comparer_l_ordre_de_deux_objets_fait_echouer_l_etape(self) -> None:
        modele = compile_template(_boucle("$.meta < $.meta2"))

        with pytest.raises(EvaluationError) as leve:
            evaluate(modele, LIGNES, BUDGET)

        assert "objet" in str(leve.value.message)

    def test_l_ordre_entre_scalaires_filtre_toujours(self) -> None:
        """Témoin : le refus porte sur les conteneurs, et sur eux seuls."""
        rendu = evaluate(compile_template(_boucle("$.id < 3")), LIGNES, BUDGET)

        assert [ligne["id"] for ligne in rendu["l"]] == [1, 2]

    def test_un_cote_absent_filtre_sans_echouer(self) -> None:
        """`null` garde son repli à `false` : des templates s'appuient dessus."""
        rendu = evaluate(compile_template(_boucle("$.absent < 3")), LIGNES, BUDGET)

        assert rendu["l"] == []
