"""Ce qu'une primitive MCP rend d'une DÉCLARATION de type d'event : le seam typé.

Même raison que `test_mcp_tool_args.py`, et le même défaut à éviter : `Caller.services`
est `Any`, donc mypy ne voit rien de ce qu'un outil MCP fait d'un service. Si
`DeclaredType` change de forme, c'est ici que ça rougit — en une seconde, et non au bout
d'une heure de campagne.

Le seam de l'ENTRÉE, lui, n'a pas de test de ce genre : ce sont les arguments de l'outil,
que le SDK valide depuis leurs annotations.
"""

from __future__ import annotations

from miles.mcp_api.tools_events import _out
from miles.workflowevents.service import DeclaredType

DEMANDE = DeclaredType(
    "shared",
    "demande_soumise",
    "Demande soumise",
    ("shared", "demande"),
    "shared/models/demande.yaml",
    ("Montant", "ExternalId"),
)


def test_une_declaration_rend_son_artefact_son_modele_et_ses_cles_dans_l_ordre() -> None:
    assert _out(DEMANDE) == {
        "scope": "shared",
        "name": "demande_soumise",
        "label": "Demande soumise",
        # L'artefact qui PORTE la déclaration : composé, jamais recopié de l'appelant.
        "path": "shared/shared.wf",
        "model": "shared/models/demande.yaml",
        "model_scope": "shared",
        "model_name": "demande",
        # L'ordre est une donnée : le moteur dérive le hash d'anti-doublon par
        # concaténation. Deux clés DISTINCTES, pour qu'un tri se voie.
        "unique": ["Montant", "ExternalId"],
        "model_missing": False,
    }


def test_l_artefact_d_un_type_de_domaine_est_celui_de_son_domaine() -> None:
    declared = DeclaredType(
        "suivi", "colis_recu", "Colis reçu", ("suivi", "colis"), "domains/suivi/models/colis.yaml"
    )

    rendu = _out(declared)

    assert (rendu["path"], rendu["unique"]) == ("domains/suivi/suivi.wf", [])


def test_un_modele_manquant_est_rendu_et_non_tu() -> None:
    """C'est ce qui bloquera l'enregistrement d'une version : le cacher ferait chercher
    ailleurs. Rendu par la liste, jamais transformé en refus."""
    absent = "shared/models/absent.yaml"
    orpheline = DeclaredType(
        "shared", "orphelin", "Orphelin", ("shared", "absent"), absent, (), True
    )

    assert _out(orpheline)["model_missing"] is True
