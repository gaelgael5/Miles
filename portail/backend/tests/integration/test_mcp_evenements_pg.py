"""Le référentiel d'événements vu par un agent : le CRUD complet, et les refus qui guident.

Ce que ces tests tiennent au-delà du CRUD : un agent qui écrit un événement ne peut pas
devenir un agent qui écrit un modèle (les deux listes restent séparées jusque dans la
surface MCP), et les deux refus propres aux événements lui arrivent NOMMÉS — un agent qui
reçoit « non conforme » sans savoir laquelle des règles il a enfreinte boucle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.integration.mcp_stack import McpForge, open_mcp_forge
from tests.integration.test_datamodels_pg import PERSONNE, body_of

pytestmark = pytest.mark.integration

WS = {"workspace_id": "retrait"}
EDIT = WS | {"branch": "edition"}
DEMANDE = "title: Demande soumise\ntype: object\nproperties:\n  Montant:\n    type: number\n"
AVEC_MODELE = (
    "title: Demande soumise\ntype: object\nproperties:\n  Montant:\n    type: number\n"
    "  Qui:\n    $ref: miles:/shared/personne\n"
)


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


def _event(content: str, name: str = "demande_soumise") -> dict[str, str]:
    return {"scope": "shared", "name": name, "content": content}


async def test_un_evenement_est_cree_lu_remplace_et_supprime_sur_une_branche_enfant(
    m: McpForge,
) -> None:
    cree = await m.ok("create_workflow_event", EDIT | _event(DEMANDE))
    rejeu = await m.ok("create_workflow_event", EDIT | _event(DEMANDE))
    change = DEMANDE + "  Dossier:\n    type: string\n"
    remplace = await m.ok("replace_workflow_event", EDIT | _event(change))
    lu = await m.ok("get_workflow_event", EDIT | {"scope": "shared", "name": "demande_soumise"})
    liste = await m.ok("list_workflow_events", EDIT)
    supprime = await m.ok(
        "delete_workflow_event", EDIT | {"scope": "shared", "name": "demande_soumise"}
    )

    assert cree["path"] == "shared/events/demande_soumise.yaml" and cree["commit"]
    # Rejeu à l'identique : rien d'écrit, et la réponse le dit plutôt que de mentir.
    assert (rejeu["unchanged"], rejeu["commit"]) == (True, None)
    assert remplace["commit"] and "Dossier" in lu["content"]
    assert "$id: miles:/events/shared/demande_soumise" in lu["content"]
    assert [e["path"] for e in liste] == ["shared/events/demande_soumise.yaml"]
    assert supprime["commit"]
    assert await m.forge.file("shared/events/demande_soumise.yaml") is None


async def test_le_socle_commun_se_lit_avant_d_ecrire(m: McpForge) -> None:
    socle = await m.ok("get_event_base", {})

    champs = {c["name"]: c for c in socle}
    assert {"Name", "Uuid", "ExternalId", "CreationDate", "EventDate", "DedupKey"} <= set(champs)
    assert champs["IntegrationDate"]["read_only"] is True


async def test_les_deux_refus_propres_aux_evenements_arrivent_NOMMES(m: McpForge) -> None:
    ferme = await m.refused(
        "create_workflow_event",
        EDIT | _event("title: D\ntype: object\nadditionalProperties: false\nproperties: {}\n"),
    )
    socle = await m.refused(
        "create_workflow_event",
        EDIT | _event("title: D\ntype: object\nproperties:\n  ExternalId:\n    type: integer\n"),
    )

    # Le NOM du refus d'abord : c'est lui qu'un agent apprend, et il doit être le même
    # que celui que rend la route de l'écran — « modele_non_conforme » enverrait un agent
    # chercher un modèle. Mesuré sur le vrai canal MCP, pas sur le mappage seul.
    assert "evenement_non_conforme" in str(ferme) and "evenement_non_conforme" in str(socle)
    assert "schema_ferme" in str(ferme)
    assert "propriete_du_socle" in str(socle)
    assert "ExternalId" in str(socle)


async def test_un_nom_que_le_DSL_refuserait_est_refuse(m: McpForge) -> None:
    refuse = await m.refused("create_workflow_event", EDIT | _event(DEMANDE, "demande-soumise"))

    assert "name" in str(refuse)


async def test_un_evenement_inconnu_se_refuse_en_NOMMANT_ceux_qui_existent(m: McpForge) -> None:
    """Un agent se corrige alors sans appel exploratoire — même geste que pour un modèle."""
    await m.ok("create_workflow_event", EDIT | _event(DEMANDE))

    refuse = await m.refused(
        "get_workflow_event", EDIT | {"scope": "shared", "name": "pas_celui_la"}
    )

    assert "evenement_inconnu" in str(refuse)
    assert "shared/events/demande_soumise.yaml" in str(refuse)


async def test_un_evenement_decrit_son_payload_avec_un_modele(m: McpForge) -> None:
    await m.ok("create_data_model", EDIT | body_of(PERSONNE))

    cree = await m.ok("create_workflow_event", EDIT | _event(AVEC_MODELE))

    assert cree["commit"]
    # Et le modèle ne peut plus être supprimé : l'événement le désigne.
    refuse = await m.refused("delete_data_model", EDIT | {"scope": "shared", "name": "personne"})
    assert "shared/events/demande_soumise.yaml" in str(refuse)


async def test_les_deux_listes_ne_se_melangent_pas_pour_un_agent_non_plus(m: McpForge) -> None:
    await m.ok("create_data_model", EDIT | body_of(PERSONNE))
    await m.ok("create_workflow_event", EDIT | _event(DEMANDE))

    modeles = await m.ok("list_data_models", EDIT)
    evenements = await m.ok("list_workflow_events", EDIT)

    assert [e["name"] for e in modeles] == ["personne"]
    assert [e["name"] for e in evenements] == ["demande_soumise"]


async def test_une_cle_seule_ne_change_aucun_evenement(m: McpForge) -> None:
    """Fail closed : une clé n'est personne, et une écriture agit comme la personne."""
    cle_seule = {"Authorization": f"Bearer {m.secret}"}

    refuse = await m.refused("create_workflow_event", EDIT | _event(DEMANDE), headers=cle_seule)

    assert "personne_requise" in str(refuse)
    assert await m.forge.file("shared/events/demande_soumise.yaml") is None
