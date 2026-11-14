"""L'artefact de déclaration des types d'event, éprouvé contre le PARSEUR DU MOTEUR.

Ces tests ne vérifient pas une forme que nous aurions décidée : ils vérifient que ce que
Miles écrit, `urban-workflow` le relit — et que ce qu'il en relit porte exactement ce qui
avait été saisi. C'est le seul contrôle qui vaille ici, parce que le consommateur de ce
fichier n'est pas Miles.
"""

from __future__ import annotations

import pytest
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.workflowevents.dsl import (
    RESERVED,
    EventType,
    FragmentError,
    fragment_path,
    model_ref,
    parse,
    ref_target,
    render,
    scope_of,
    writable,
)

COLIS = EventType("colis_recu", "Colis reçu", ("livraison", "colis"), ("Tracking", "Site"))
PING = EventType("ping", "Ping", ("shared", "ping"))


def test_l_artefact_d_un_perimetre_vit_dans_ce_perimetre() -> None:
    assert fragment_path("shared") == "shared/shared.wf"
    assert fragment_path("livraison") == "domains/livraison/livraison.wf"


def test_le_chemin_de_l_artefact_se_relit_vers_son_perimetre() -> None:
    assert scope_of("shared/shared.wf") == "shared"
    assert scope_of("domains/livraison/livraison.wf") == "livraison"
    # Un `.wf` ailleurs, ou mal nommé, n'est pas l'artefact d'un périmètre : il serait
    # rapporté comme un emplacement inattendu, pas chargé comme un référentiel.
    assert scope_of("domains/livraison/autre.wf") is None
    assert scope_of("shared/models/colis.yaml") is None


def test_une_reference_porte_la_portee_car_le_registre_du_moteur_est_plat() -> None:
    assert model_ref("shared", "colis") == "shared.colis"
    assert model_ref("livraison", "colis") == "domains.livraison.colis"
    assert ref_target("shared.colis") == ("shared", "colis")
    assert ref_target("domains.livraison.colis") == ("livraison", "colis")
    assert ref_target("colis") is None


def test_un_perimetre_sans_type_d_event_n_a_pas_d_artefact() -> None:
    """Un FRAGMENT sans déclaration est une erreur de syntaxe pour le moteur : poser le
    fichier quand même ferait échouer le chargement de tout le répertoire."""
    assert render("shared", []) == ""


def test_ce_que_miles_ecrit_le_moteur_le_relit_sans_une_erreur() -> None:
    text = render("livraison", [COLIS, PING])

    script = WorkflowScriptParser.parse_string(text, "livraison.wf")

    assert [(e.line, e.column, e.message) for e in script.errors] == []
    assert script.is_fragment


def test_l_aller_retour_conserve_le_libelle_le_modele_et_l_ordre_des_cles() -> None:
    """L'ordre des clés d'unicité est une DONNÉE : le moteur en dérive un hash par
    concaténation, donc deux ordres donnent deux hashs et deux anti-doublons."""
    relu = parse(render("livraison", [COLIS, PING]))

    assert relu == [COLIS, PING]
    assert relu[0].unique == ("Tracking", "Site")


def test_un_libelle_a_apostrophe_survit_a_l_aller_retour() -> None:
    """`''` est l'échappement du DSL. Sans lui, « L'accusé » couperait la chaîne et le
    reste de la ligne deviendrait du code."""
    accuse = EventType("accuse", "L'accusé de réception", ("shared", "accuse"))

    assert parse(render("shared", [accuse])) == [accuse]


def test_le_moteur_ne_voit_aucun_event_technique_dans_un_artefact() -> None:
    """Le moteur ajoute ses events réservés en construisant un workflow complet. Un
    fragment n'est pas construit : ce qu'on relit est exactement ce qu'on a écrit."""
    assert [t.name for t in parse(render("shared", [PING]))] == ["ping"]


def test_un_artefact_illisible_est_refuse_en_donnant_la_position() -> None:
    with pytest.raises(FragmentError) as refus:
        parse("FRAGMENT NAME shared\nDEFINE EVENT ;\n")

    assert refus.value.problems[0].line == 2


def test_un_script_complet_n_est_pas_un_artefact_de_perimetre() -> None:
    """Il déclare un workflow, pas un référentiel : le charger d'ici ferait entrer des
    états et des transitions par un écran qui n'en montre pas."""
    with pytest.raises(FragmentError):
        parse("NAME livraison VERSION 1\nDEFINE EVENT a 'A' AS @shared.a;\n")


def test_un_nom_declare_deux_fois_est_refuse_par_le_moteur_pas_par_nous() -> None:
    """Le moteur lève ce doublon pendant la VISITE, pas à l'analyse syntaxique : sans
    reprise explicite, son exception traverserait jusqu'à la route."""
    with pytest.raises(FragmentError):
        parse(
            "FRAGMENT NAME shared\n"
            "DEFINE EVENT a 'A' AS @shared.a;\n"
            "DEFINE EVENT a 'B' AS @shared.b;\n"
        )


def test_une_cle_d_unicite_repetee_est_refusee() -> None:
    with pytest.raises(FragmentError):
        parse("FRAGMENT NAME shared\nDEFINE EVENT a 'A' AS @shared.a UNIQUE (X, X);\n")


def test_ce_que_le_dsl_ne_sait_pas_ecrire_est_reconnu_comme_tel() -> None:
    """Le tiret est admis dans un nom de modèle ou de domaine, et refusé par le DSL : le
    savoir ICI, c'est refuser à la saisie au lieu de livrer un artefact illisible."""
    assert writable("colis_recu")
    assert writable("Tracking")
    assert not writable("mon-domaine")
    assert not writable("2champs")
    assert not writable("_champ")
    assert not writable("côté")


def test_un_mot_reserve_du_dsl_n_est_pas_ecrivable() -> None:
    """La liste est LUE du lexer installé : une montée du moteur qui en ajoute un est
    couverte sans que personne ne vienne ici."""
    assert "EVENT" in RESERVED
    assert not writable("EVENT")
    # Le lexer est sensible à la casse : `State` n'est pas `STATE`, et passe.
    assert writable("State")
