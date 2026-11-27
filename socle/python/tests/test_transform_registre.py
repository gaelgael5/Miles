"""Le registre de Miles contre celui du moteur : rien ne se perd à la reconstruction.

`miles_socle.transform.engine._registry()` ne prend pas le registre du moteur tel quel —
il le RECONSTRUIT, pour n'en garder que le cœur (un plugin installé ne doit pas se glisser
dans le profil d'écriture) et pour y substituer sa propre conversion. Reconstruire veut
dire recopier, et deux montées de version ont déjà prouvé qu'une recopie champ par champ
perd ce que la suivante ajoute :

- urban-json 0.6.0 a ajouté `lazy_args` ; neuf fonctions du cœur en déclarent, et sans ce
  champ elles recevaient des arguments ÉVALUÉS là où elles attendent un callable. Rien ne
  levait : `sort` rendait la liste dans son ordre d'entrée, `trydefault` laissait filer
  l'erreur qu'il rattrape.
- urban-json 0.9.0 porte dix fonctions paresseuses de plus (`filter`, `map`, `ifelse`,
  `every`, `some`, `find`, `findindex`, `reduce`, `minby`, `maxby`).

D'où la garde de ce fichier : **plus aucune liste de champs à tenir à la main**. On compare
la description COMPLÈTE que chaque registre donne de la même fonction. Un champ qu'une
version future ajoutera fera rougir ce test le jour de la montée, pas six mois plus tard
sur un terminal.
"""

from __future__ import annotations

from typing import Any, ClassVar

from urban_json import default_registry

from miles_socle.transform.engine import (
    CAST_FUNCTION,
    compile_template,
    evaluate,
    function_registry,
)

BUDGET = 100_000


def _coeur() -> list[str]:
    """Les fonctions du cœur du moteur, telles que `_registry()` les sélectionne."""
    noms = []
    for nom in default_registry.names():
        info = default_registry.describe(nom)
        if info is None or info.kind != "function":
            continue
        if not info.function.__module__.startswith("urban_json.functions."):
            continue
        noms.append(nom)
    return noms


class TestLaReconstructionNePerdRien:
    def test_chaque_fonction_du_coeur_est_decrite_a_l_identique(self) -> None:
        miles = function_registry()

        ecarts = []
        for nom in _coeur():
            if nom == CAST_FUNCTION:
                continue  # Écart VOULU : la conversion de Miles est stricte (voir engine).
            attendu = default_registry.describe(nom)
            rendu = miles.describe(nom)
            assert attendu is not None
            if rendu is None or rendu.to_dict() != attendu.to_dict():
                ecarts.append(nom)

        assert ecarts == []

    def test_la_fonction_enregistree_est_celle_du_moteur_et_non_une_enveloppe(self) -> None:
        """`info.function` et non `get(nom)` : `get` rend une enveloppe de contrôle d'arité.

        C'est par cette enveloppe que la garde « seul le cœur entre » est tombée en
        silence en 0.2.1 — son `__module__` est celui du registre, pas celui du cœur.
        """
        miles = function_registry()

        for nom in ("sort", "upper", "groupby"):
            rendu = miles.describe(nom)
            attendu = default_registry.describe(nom)
            assert rendu is not None and attendu is not None
            assert rendu.function is attendu.function

    def test_seule_la_conversion_diverge_du_moteur(self) -> None:
        """Discriminant : si un jour un deuxième écart s'installait, il serait nommé ici."""
        miles = function_registry()

        divergents = [
            nom
            for nom in _coeur()
            if (info := miles.describe(nom)) is not None
            and (origine := default_registry.describe(nom)) is not None
            and info.function is not origine.function
        ]

        assert divergents == [CAST_FUNCTION]


class TestLesPositionsParesseusesDesFonctionsNeuves:
    """Les dix fonctions paresseuses d'urban-json 0.9.0, éprouvées par leur COMPORTEMENT.

    La garde de champ ci-dessus suffirait à voir une perte, mais elle compare deux
    registres : si le moteur lui-même cessait de déclarer une position paresseuse, elle
    resterait verte. Ces cas-là passent par l'évaluation, avec des jeux d'essai dont le
    résultat serait DIFFÉRENT si l'argument arrivait évalué.
    """

    # `ok` manque sur la deuxième ligne, et l'ordre d'entrée ne suit pas la clef `n` :
    # un prédicat évalué une seule fois, ou une clef ignorée, se verrait.
    LIGNES: ClassVar[dict[str, Any]] = {
        "l": [{"n": 3, "v": "c", "ok": True}, {"n": 1, "v": "a"}, {"n": 2, "v": "b", "ok": True}]
    }

    def test_filter_ne_garde_que_ce_que_le_predicat_retient(self) -> None:
        """Le prédicat est un CHEMIN, pas une comparaison : voir la note de fin de fichier."""
        rendu = evaluate(compile_template('{ "t": filter($.l, $.ok) }'), self.LIGNES, BUDGET)

        # Évalué une fois dans la portée du dessus, `$.ok` serait absent : zéro ligne.
        assert [e["n"] for e in rendu["t"]] == [3, 2]

    def test_map_applique_l_expression_a_chaque_element(self) -> None:
        rendu = evaluate(compile_template('{ "t": map($.l, $.v) }'), self.LIGNES, BUDGET)

        assert rendu["t"] == ["c", "a", "b"]

    def test_ifelse_n_evalue_que_la_branche_retenue(self) -> None:
        """La branche non prise LÈVERAIT si elle était évaluée : c'est la preuve."""
        rendu = evaluate(
            compile_template('{ "t": ifelse(false, parsenumber("pas un nombre"), "repli") }'),
            {},
            BUDGET,
        )

        assert rendu["t"] == "repli"

    def test_minby_et_maxby_comparent_la_clef_et_non_l_ordre_d_entree(self) -> None:
        source = '{ "min": minby($.l, $.n), "max": maxby($.l, $.n) }'

        rendu = evaluate(compile_template(source), self.LIGNES, BUDGET)

        assert (rendu["min"]["v"], rendu["max"]["v"]) == ("a", "c")

    def test_every_et_some_lisent_le_predicat_ligne_par_ligne(self) -> None:
        source = '{ "tous": every($.l, $.ok), "au_moins_un": some($.l, $.ok) }'

        rendu = evaluate(compile_template(source), self.LIGNES, BUDGET)

        # Deux lignes sur trois portent `ok` : la réponse diffère selon la fonction, ce
        # qui ne serait pas le cas d'un prédicat évalué une fois pour toutes.
        assert (rendu["tous"], rendu["au_moins_un"]) == (False, True)


# ---------------------------------------------------------------------------
# MESURE DU 27/11/2026, à ne pas perdre : parmi les vingt-huit fonctions qui entrent
# avec 0.9.0, celles dont l'argument paresseux est un PRÉDICAT (`filter`, `every`,
# `some`, `find`, `findindex`) ne s'écrivent dans Miles qu'avec un chemin —
# `filter($.l, $.ok)`. La forme naturelle, `filter($.l, $.v == "a")`, est REFUSÉE par le
# profil d'écriture, qui n'admet une comparaison que comme prédicat d'un `$where`. Le
# catalogue de l'intellisense les propose donc sans que le profil accepte la façon dont
# on s'en sert d'ordinaire. Élargir le profil est une décision de cadrage, pas une
# correction au passage : c'est signalé à l'humain, et rien n'a été élargi ici.
