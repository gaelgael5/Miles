"""L'édition conservatrice de l'artefact d'un périmètre (bug `ff8779c6`).

Ce que ces tests tiennent : le portail ne détruit plus ce qu'il n'écrit pas. Module PUR —
du texte entre, du texte sort —, donc éprouvé sans dépôt ni forge, et chaque sortie est
relue par le PARSEUR DU MOTEUR, jamais seulement comparée à une chaîne.
"""

from __future__ import annotations

import pytest
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.workflowevents.artefact import (
    ACTION,
    ARTIFACT,
    CONST,
    EVENT,
    RULE,
    declarations,
    rewrite,
)
from miles.workflowevents.dsl import EventType, FragmentError

DEMANDE = EventType("demande_soumise", "Demande soumise", ("shared", "demande"))
RECUE = EventType("demande_recue", "Demande reçue", ("shared", "demande"), ("Montant",))

CINQ_SORTES = (
    "FRAGMENT NAME shared\n"
    "DESCRIPTION 'Référentiel transverse'\n"
    "\n"
    "DEFINE CONST Seuil 12 'Seuil de poids';\n"
    "DEFINE EVENT demande_soumise 'Demande soumise' AS @shared.demande;\n"
    "DEFINE RULE estGrand (INTEGER poids) 'Est grand' AS @regles.grand;\n"
    "DEFINE ACTION notifier (TEXT destinataire) 'Notifier';\n"
    "DEFINE ARTIFACT Corps 'Corps HTTP' USING @scripts.corps;\n"
)
# Ce que le portail n'écrit pas, et qui doit traverser chaque geste à l'octet près.
GARDEES = (
    "DESCRIPTION 'Référentiel transverse'",
    "DEFINE CONST Seuil 12 'Seuil de poids';",
    "DEFINE RULE estGrand (INTEGER poids) 'Est grand' AS @regles.grand;",
    "DEFINE ACTION notifier (TEXT destinataire) 'Notifier';",
    "DEFINE ARTIFACT Corps 'Corps HTTP' USING @scripts.corps;",
)


def charge(text: str) -> str:
    """Le texte, relu par le moteur. Rend le texte pour qu'une assertion s'enchaîne."""
    script = WorkflowScriptParser.parse_string(text, "")
    assert [(e.line, e.message) for e in script.errors] == [], text
    assert script.is_fragment
    return text


def test_les_cinq_sortes_sont_situees_au_caractere_pres() -> None:
    found = declarations(CINQ_SORTES)

    assert [(d.kind, d.name) for d in found] == [
        (CONST, "Seuil"),
        (EVENT, "demande_soumise"),
        (RULE, "estGrand"),
        (ACTION, "notifier"),
        (ARTIFACT, "Corps"),
    ]
    # L'étendue va du `D` de DEFINE au `;` compris : c'est ce qui permet de remplacer une
    # déclaration sans toucher au caractère d'avant ni à celui d'après.
    assert [CINQ_SORTES[d.start : d.end] for d in found] == [
        "DEFINE CONST Seuil 12 'Seuil de poids';",
        "DEFINE EVENT demande_soumise 'Demande soumise' AS @shared.demande;",
        "DEFINE RULE estGrand (INTEGER poids) 'Est grand' AS @regles.grand;",
        "DEFINE ACTION notifier (TEXT destinataire) 'Notifier';",
        "DEFINE ARTIFACT Corps 'Corps HTTP' USING @scripts.corps;",
    ]


def test_declarer_un_type_garde_les_quatre_autres_sortes_a_l_octet_pres() -> None:
    written = charge(rewrite(CINQ_SORTES, "shared", [DEMANDE, RECUE]))

    for gardee in GARDEES:
        assert gardee in written, f"déclaration perdue : {gardee}"
    assert (
        "DEFINE EVENT demande_recue 'Demande reçue' AS @shared.demande UNIQUE (Montant);" in written
    )


def test_modifier_un_type_le_remplace_A_SA_PLACE() -> None:
    """L'ordre reste stable d'un geste à l'autre (critère 5) : deux gestes successifs ne
    doivent pas faire danser le fichier dans l'historique git."""
    changed = EventType("demande_soumise", "Demande reçue", ("shared", "demande"))

    written = charge(rewrite(CINQ_SORTES, "shared", [changed]))

    avant, apres = CINQ_SORTES.splitlines(), written.splitlines()
    changees = [(a, b) for a, b in zip(avant, apres, strict=True) if a != b]
    assert len(changees) == 1, changees
    assert changees[0][1] == "DEFINE EVENT demande_soumise 'Demande reçue' AS @shared.demande;"


def test_supprimer_le_dernier_type_GARDE_le_fichier_quand_il_reste_autre_chose() -> None:
    """LE défaut du bug : le fichier était retiré dès qu'il n'y avait plus de type d'event,
    ce qui emportait la règle, l'action, l'artefact et la constante avec lui."""
    written = charge(rewrite(CINQ_SORTES, "shared", []))

    for gardee in GARDEES:
        assert gardee in written, f"déclaration perdue : {gardee}"
    assert "DEFINE EVENT" not in written
    # Et pas de ligne vide laissée derrière la déclaration retirée.
    assert "\n\n\n" not in written


def test_supprimer_le_seul_type_d_un_artefact_qui_ne_porte_rien_d_autre_rend_le_vide() -> None:
    # Un FRAGMENT sans aucune déclaration est une erreur de syntaxe du moteur : le fichier
    # se retire, et c'est l'appelant qui le fait sur une chaîne vide (critère 4).
    seul = (
        "FRAGMENT NAME shared\n\n"
        "DEFINE EVENT demande_soumise 'Demande soumise' AS @shared.demande;\n"
    )

    assert rewrite(seul, "shared", []) == ""


def test_un_artefact_absent_s_ecrit_en_entier() -> None:
    # Rien à conserver : le rendu complet, comme avant. Et le cas « rien trouvé » inclut
    # un fichier présent mais vide, qu'un outil tiers aurait pu laisser.
    written = charge(rewrite(None, "shared", [DEMANDE]))
    aussi = charge(rewrite("   \n", "shared", [DEMANDE]))

    assert written.startswith("FRAGMENT NAME shared\n")
    assert written == aussi
    assert rewrite(None, "shared", []) == ""


def test_un_artefact_de_domaine_garde_son_en_tete() -> None:
    # Discriminant : le périmètre n'est pas « shared », et l'en-tête ne doit pas être
    # réécrit avec le mauvais nom — il n'est pas réécrit du tout.
    domaine = (
        "FRAGMENT NAME achats\n\n"
        "DEFINE RULE estGrand (INTEGER poids) 'Est grand' AS @regles.grand;\n"
    )
    commande = EventType("commande_validee", "Commande validée", ("achats", "commande"))

    written = charge(rewrite(domaine, "achats", [commande]))

    assert written.startswith("FRAGMENT NAME achats\n")
    assert (
        "DEFINE EVENT commande_validee 'Commande validée' AS @domains.achats.commande;" in written
    )
    assert "DEFINE RULE estGrand" in written


def test_un_artefact_illisible_n_est_PAS_edite() -> None:
    """On ne réécrit jamais par-dessus ce qu'on n'a pas su relire : ce serait perdre tout
    ce que le fichier portait, pour une faute de frappe d'un tiers."""
    with pytest.raises(FragmentError):
        rewrite("FRAGMENT NAME shared\nDEFINE EVENT ;\n", "shared", [DEMANDE])


def test_une_sorte_que_miles_ne_nomme_pas_serait_conservee() -> None:
    """Garde de fond : la conservation ne tient pas à la liste des sortes que Miles
    énumère. Elle tient à ce que seules les étendues des types d'event sont réécrites —
    donc une sorte ajoutée par une montée du moteur traverse sans qu'on vienne ici.

    Éprouvé par le seul moyen honnête : la constante, sorte que le portail n'écrit pas,
    survit à un geste qui ne la nomme nulle part.
    """
    porte_une_const = (
        "FRAGMENT NAME shared\n\n"
        "DEFINE CONST Seuil 12 'Seuil de poids';\n"
        "DEFINE EVENT demande_soumise 'Demande soumise' AS @shared.demande;\n"
    )

    written = charge(rewrite(porte_une_const, "shared", [RECUE]))

    assert "DEFINE CONST Seuil 12 'Seuil de poids';" in written
    assert "demande_soumise" not in written
    assert "demande_recue" in written
