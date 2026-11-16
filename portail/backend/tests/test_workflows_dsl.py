"""L'en-tête d'un script de workflow : ce qu'on en lit, et ce qu'on refuse.

Mesuré, jamais déduit : chaque cas de ce fichier a été passé au parseur du moteur avant
d'être écrit ici (`urban-workflow 0.4.0`, 16/11/2026).
"""

from __future__ import annotations

import pytest

from miles.workflows.dsl import ScriptError, quoted, read_header, render_new, unquoted


def test_un_script_reduit_a_son_nom_se_relit_et_ne_declare_aucun_etat() -> None:
    """La forme que `render_new` produit doit être lisible, sinon créer casse la branche."""
    header = read_header("NAME retrait_comptoir\n")
    assert (header.name, header.label, header.version) == ("retrait_comptoir", None, None)
    assert (header.includes, header.states) == ((), 0)


def test_le_script_cree_par_miles_se_relit_avec_son_libelle() -> None:
    """L'aller-retour de la création : c'est ce que la liste affichera juste après.

    Discriminant : le libellé passe par les quotes du DSL, donc un échappement raté se
    verrait ici et non six écrans plus loin.
    """
    header = read_header(render_new("retrait_comptoir", "Retrait au comptoir"))
    assert (header.name, header.label) == ("retrait_comptoir", "Retrait au comptoir")


def test_une_apostrophe_dans_le_libelle_traverse_l_aller_retour() -> None:
    # `''` est l'échappement du DSL. Sans lui, « L'attente » ferme la chaîne et le script
    # devient illisible — un refus qui n'accuserait pas sa cause.
    header = read_header(render_new("attente", "L'attente du client"))
    assert header.label == "L'attente du client"


def test_la_version_et_les_inclusions_se_lisent_dans_l_ordre_ecrit() -> None:
    """L'ordre des `INCLUDE` est une donnée : le chargeur visite les fragments dans cet
    ordre, et deux ordres peuvent résoudre deux choses différentes."""
    header = read_header(
        "INCLUDE 'shared.wf'\n"
        "INCLUDE 'livraison.wf'\n"
        "NAME retrait_comptoir VERSION 3\n"
        "DESCRIPTION 'Retrait'\n"
    )
    assert header.includes == ("shared.wf", "livraison.wf")
    assert header.version == 3


def test_les_etats_declares_sont_comptes() -> None:
    header = read_header(
        "NAME retrait\nDESCRIPTION 'Retrait'\n"
        "DEFINE STATE attente 'En attente'\n"
        "  ON EVENT colis_recu SWITCH remis;\n"
        "DEFINE STATE remis 'Remis';\n"
    )
    assert header.states == 2


def test_un_fragment_n_est_pas_un_workflow() -> None:
    """Un artefact de périmètre rangé dans `workflows/` est un écart, pas un workflow.

    Le laisser passer ferait apparaître un référentiel de types d'event dans la liste des
    workflows, sous un nom qui ne désigne aucun comportement.
    """
    with pytest.raises(ScriptError) as refus:
        read_header("FRAGMENT NAME shared\nDEFINE EVENT colis_recu 'Colis reçu';\n")
    assert "FRAGMENT" in refus.value.problems[0].message


def test_un_script_illisible_rend_tous_ses_manquements_positionnes() -> None:
    """Positionnés comme le moteur les positionne : l'écran montre la ligne fautive."""
    with pytest.raises(ScriptError) as refus:
        read_header("NAME retrait\nDEFINE STATE 'sans clef';\n")
    assert refus.value.problems
    assert all(p.line > 0 for p in refus.value.problems)


def test_un_libelle_vide_n_est_pas_ecrivable() -> None:
    """`''` est une erreur de LEXER, mesurée : un workflow a toujours un libellé.

    Ce test dit pourquoi `checked_label` refuse le vide en amont — sans lui, la création
    produirait un fichier que le moteur refuse.
    """
    with pytest.raises(ScriptError):
        read_header(render_new("retrait", ""))


@pytest.mark.parametrize("label", ["Retrait", "L'attente", "Deux '' quotes", ""])
def test_quoted_et_unquoted_sont_inverses(label: str) -> None:
    assert unquoted(quoted(label)) == label
