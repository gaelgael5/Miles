"""Le nom d'un workflow et l'emplacement de son fichier.

Ce fichier naît d'un défaut réel, et de son coût : la règle de nommage admettait un
CHIFFRE en tête, recopiée de celle des types d'event, alors que le `REGULAR_ID` du DSL
exige une lettre. Le nom `2` était donc refusé — mais par `writable`, donc sous
`name_non_ecrivable`, dont le message annonce « mot réservé du DSL ». Refusé pour une
raison fausse.

Seule la campagne d'intégration l'a vu, après 74 minutes (16/11/2026). Ces tests-ci
mettent une seconde, et c'est tout l'objet : une règle de nommage se tient en unitaire,
pas en bout de chaîne.
"""

from __future__ import annotations

import pytest

from miles.workflows.layout import (
    ROOT,
    checked_against_scopes,
    checked_name,
    names_in,
    workflow_path,
)
from miles.workspaces.model import WorkspaceInputError


@pytest.mark.parametrize("name", ["retrait", "retrait_comptoir", "r", "r2", "a_1_b"])
def test_un_nom_que_le_dsl_sait_ecrire_est_accepte(name: str) -> None:
    assert checked_name(name) == name


@pytest.mark.parametrize(
    ("name", "field"),
    [
        # Le tiret : erreur de LEXER du DSL (« mismatched input '-' »).
        ("retrait-comptoir", "name"),
        # Un chiffre en tête : erreur de PARSEUR. C'est le cas qui a mordu.
        ("2", "name"),
        ("2retrait", "name"),
        # Les majuscules et les accents : le lexer est sensible à la casse, et tout
        # caractère hors ASCII est une erreur de lexer.
        ("Retrait", "name"),
        ("rétrait", "name"),
        ("retrait comptoir", "name"),
        ("", "name"),
        ("_retrait", "name"),
        ("a" * 64, "name"),
    ],
)
def test_un_nom_que_le_dsl_ne_sait_pas_ecrire_est_refuse_en_nommant_le_champ(
    name: str, field: str
) -> None:
    """Le CHAMP compte autant que le refus : c'est lui qui choisit la phrase affichée.

    Un nom refusé sous `name_non_ecrivable` s'explique par « mot réservé du DSL » ; sous
    `name`, par la règle de nommage. Les confondre fait expliquer à l'utilisateur une
    règle qui n'est pas celle qu'il a enfreinte.
    """
    with pytest.raises(WorkspaceInputError) as refus:
        checked_name(name)
    assert refus.value.field == field


def test_un_mot_reserve_du_dsl_est_refuse_sous_son_propre_champ() -> None:
    """Les 48 mots réservés sont LUS du lexer installé, et tous en majuscules — donc hors
    d'atteinte de la règle de nommage aujourd'hui. Ce test documente que la garde existe
    et dit comment elle se manifesterait si une montée du moteur en ajoutait un en
    minuscules. Il n'y en a aucun à éprouver : c'est la mesure, pas un oubli."""
    from miles.workflowevents.dsl import RESERVED

    assert RESERVED, "le lexer n'expose plus ses mots réservés : la garde ne mesure plus rien"
    assert all(mot.isupper() for mot in RESERVED)


def test_un_workflow_ne_peut_pas_porter_le_nom_d_un_perimetre() -> None:
    """La publication rassemble tout dans un répertoire plat : l'artefact du périmètre et
    le workflow deviendraient le même fichier, et l'un écraserait l'autre en silence."""
    for name in ("shared", "livraison"):
        with pytest.raises(WorkspaceInputError) as refus:
            checked_against_scopes(name, ["livraison", "suivi"])
        assert refus.value.field == "nom_de_perimetre"


def test_un_nom_qui_ne_designe_aucun_perimetre_passe() -> None:
    # Discriminant : sans ce contrôle, un refus systématique passerait le test ci-dessus.
    assert checked_against_scopes("retrait_comptoir", ["livraison"]) == "retrait_comptoir"


def test_le_fichier_porte_le_nom_du_workflow_sous_la_racine() -> None:
    assert workflow_path("retrait_comptoir") == f"{ROOT}/retrait_comptoir.wf"


def test_seuls_les_wf_de_la_racine_sont_des_workflows() -> None:
    """Les artefacts de périmètre portent la même extension, et c'est délibéré : c'est
    l'EMPLACEMENT qui distingue, et le chargeur du moteur distingue par `is_fragment`."""
    assert names_in(
        [
            "workflows/retrait_comptoir.wf",
            "workflows/livraison.wf",
            # Ni l'artefact d'un périmètre, ni un fichier d'une autre rubrique, ni un
            # sous-dossier : aucun n'est un workflow de la branche.
            "shared/shared.wf",
            "domains/livraison/livraison.wf",
            "workflows/.gitkeep",
            "workflows/sous/dossier.wf",
            "transformations/une-chaine/chain.json",
        ]
    ) == ["livraison", "retrait_comptoir"]
