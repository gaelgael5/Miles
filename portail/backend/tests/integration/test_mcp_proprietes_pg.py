"""Modifier UNE propriété par MCP : le petit artefact, et ce qu'il ne détruit pas.

La promesse de ces primitives (Gael, 11/11/2026) est double : l'appel est petit, ET ce
qu'il ne nomme pas ne bouge pas. C'est la seconde moitié qu'il faut mesurer sur le vrai
dépôt — un test unitaire sur la mutation ne dit rien de ce que le fichier devient après
normalisation, réécriture et commit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml

from miles.datamodels.schema import normalized
from tests.integration.mcp_stack import McpForge, open_mcp_forge

pytestmark = pytest.mark.integration

WS = {"workspace_id": "retrait"}
EDIT = WS | {"branch": "edition"}
MODELE = {"kind": "model"}
EVENEMENT = {"kind": "event"}

# Un modèle qui porte ce qu'un remplacement entier écrit à la main perdrait : un `$defs`,
# un mot-clef d'extension, et une propriété qu'on ne nomme pas dans l'appel.
COLIS = normalized(
    """title: Colis
type: object
required: [reference]
properties:
  reference:
    type: string
    format: uuid
  poids:
    type: number
    x-miles:
      usage: etiquette
  tarif:
    $ref: "#/$defs/tarif"
$defs:
  tarif:
    type: number
""",
    "shared",
    "colis",
)
PERSONNE = normalized(
    "title: Personne\ntype: object\nproperties:\n  nom:\n    type: string\n", "shared", "personne"
)
EVENT = "title: Demande\ntype: object\nproperties:\n  Montant:\n    type: number\n"


@pytest.fixture
async def m(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_mcp_forge(blank_db, tmp_path) as opened:
        yield opened


async def _colis(m: McpForge) -> None:
    await m.ok(
        "create_schema", MODELE | EDIT | {"scope": "shared", "name": "colis", "content": COLIS}
    )


async def _ecrit(m: McpForge, path: str = "shared/models/colis.yaml") -> dict:
    """Le fichier tel que la forge le montre, une fois publié."""
    text = await m.forge.file(path)
    assert text is not None, path
    document = yaml.safe_load(text)
    assert isinstance(document, dict)
    return document


async def test_une_propriete_s_ajoute_sans_rien_perdre_du_reste(m: McpForge) -> None:
    await _colis(m)

    pose = await m.ok(
        "set_schema_property",
        MODELE
        | EDIT
        | {"scope": "shared", "name": "colis", "path": ["etat"], "schema": "type: string"},
    )

    assert pose["commit"] and pose["unchanged"] is False
    ecrit = await _ecrit(m)
    assert ecrit["properties"]["etat"] == {"type": "string"}
    # Ce que l'appel n'a pas nommé : intact, octet pour octet dans son contenu.
    assert ecrit["$defs"] == {"tarif": {"type": "number"}}
    assert ecrit["properties"]["poids"]["x-miles"] == {"usage": "etiquette"}
    assert ecrit["properties"]["reference"]["format"] == "uuid"
    assert ecrit["required"] == ["reference"]
    assert ecrit["$id"] == "miles:/shared/colis"


async def test_la_propriete_posee_peut_naitre_obligatoire(m: McpForge) -> None:
    await _colis(m)

    await m.ok(
        "set_schema_property",
        MODELE
        | EDIT
        | {
            "scope": "shared",
            "name": "colis",
            "path": ["etat"],
            "schema": "type: string",
            "required": True,
        },
    )

    assert (await _ecrit(m))["required"] == ["reference", "etat"]


async def test_une_propriete_retiree_perd_son_obligation_avec_elle(m: McpForge) -> None:
    await _colis(m)

    await m.ok(
        "remove_schema_property",
        MODELE | EDIT | {"scope": "shared", "name": "colis", "path": ["reference"]},
    )

    ecrit = await _ecrit(m)
    assert "reference" not in ecrit["properties"]
    # Laisser `required: [reference]` ferait un schéma qu'aucun document ne satisfait.
    assert "required" not in ecrit
    assert set(ecrit["properties"]) == {"poids", "tarif"}


async def test_la_version_monte_a_chaque_propriete_posee(m: McpForge) -> None:
    await _colis(m)

    await m.ok(
        "set_schema_property",
        MODELE
        | EDIT
        | {"scope": "shared", "name": "colis", "path": ["a"], "schema": "type: string"},
    )
    await m.ok(
        "set_schema_property",
        MODELE
        | EDIT
        | {"scope": "shared", "name": "colis", "path": ["b"], "schema": "type: string"},
    )

    assert await m.forge.file("shared/models/colis.meta.yaml") == "version: 3\n"


async def test_poser_deux_fois_la_meme_propriete_n_ecrit_rien_la_seconde(m: McpForge) -> None:
    await _colis(m)
    args = (
        MODELE
        | EDIT
        | {
            "scope": "shared",
            "name": "colis",
            "path": ["etat"],
            "schema": "type: string",
        }
    )

    await m.ok("set_schema_property", args)
    rejeu = await m.ok("set_schema_property", args)

    assert (rejeu["unchanged"], rejeu["commit"]) == (True, None)


async def test_un_renvoi_s_ajoute_par_la_MEME_primitive(m: McpForge) -> None:
    """Pas de primitive à part pour les renvois : c'est une propriété comme une autre."""
    await m.ok(
        "create_schema",
        MODELE | EDIT | {"scope": "shared", "name": "personne", "content": PERSONNE},
    )
    await _colis(m)

    await m.ok(
        "set_schema_property",
        MODELE
        | EDIT
        | {
            "scope": "shared",
            "name": "colis",
            "path": ["destinataire"],
            "schema": "$ref: miles:/shared/personne",
        },
    )

    assert (await _ecrit(m))["properties"]["destinataire"] == {"$ref": "miles:/shared/personne"}


async def test_un_renvoi_vers_un_modele_absent_est_refuse_comme_ailleurs(m: McpForge) -> None:
    """La validation est celle d'un remplacement entier : le petit artefact n'ouvre
    aucune porte que le grand n'ouvrait pas."""
    await _colis(m)

    refuse = await m.refused(
        "set_schema_property",
        MODELE
        | EDIT
        | {
            "scope": "shared",
            "name": "colis",
            "path": ["destinataire"],
            "schema": "$ref: miles:/shared/fantome",
        },
    )

    assert "modele_non_conforme" in str(refuse)
    assert "shared/fantome" in str(refuse)


async def test_un_chemin_fautif_est_refuse_en_NOMMANT_ce_qui_existe(m: McpForge) -> None:
    await _colis(m)

    refuse = await m.refused(
        "remove_schema_property",
        MODELE | EDIT | {"scope": "shared", "name": "colis", "path": ["absente"]},
    )

    assert "propriete_inconnue" in str(refuse)
    assert "reference" in str(refuse) and "poids" in str(refuse)


async def test_la_meme_primitive_modifie_un_EVENEMENT(m: McpForge) -> None:
    await m.ok(
        "create_schema",
        EVENEMENT | EDIT | {"scope": "shared", "name": "demande_soumise", "content": EVENT},
    )

    await m.ok(
        "set_schema_property",
        EVENEMENT
        | EDIT
        | {
            "scope": "shared",
            "name": "demande_soumise",
            "path": ["Dossier"],
            "schema": "type: string",
        },
    )

    ecrit = await _ecrit(m, "shared/events/demande_soumise.yaml")
    assert set(ecrit["properties"]) == {"Montant", "Dossier"}
    assert ecrit["$id"] == "miles:/events/shared/demande_soumise"


async def test_le_socle_reste_refuse_meme_par_une_seule_propriete(m: McpForge) -> None:
    """Le chemin court ne contourne pas la règle du moteur."""
    await m.ok(
        "create_schema",
        EVENEMENT | EDIT | {"scope": "shared", "name": "demande_soumise", "content": EVENT},
    )

    refuse = await m.refused(
        "set_schema_property",
        EVENEMENT
        | EDIT
        | {
            "scope": "shared",
            "name": "demande_soumise",
            "path": ["ExternalId"],
            "schema": "type: integer",
        },
    )

    assert "evenement_non_conforme" in str(refuse)
    assert "propriete_du_socle" in str(refuse)


async def test_une_cle_seule_ne_modifie_aucune_propriete(m: McpForge) -> None:
    await _colis(m)
    cle_seule = {"Authorization": f"Bearer {m.secret}"}

    refuse = await m.refused(
        "set_schema_property",
        MODELE
        | EDIT
        | {"scope": "shared", "name": "colis", "path": ["etat"], "schema": "type: string"},
        headers=cle_seule,
    )

    assert "personne_requise" in str(refuse)
    assert "etat" not in (await _ecrit(m))["properties"]
