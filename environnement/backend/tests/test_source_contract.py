from __future__ import annotations

from typing import Any

from environnement.ingestion.methods import Method
from environnement.ingestion.source_contract import source_spec

MODELE: dict[str, Any] = {"type": "object", "properties": {"code": {"type": "string"}}}
SPEC: dict[str, Any] = {
    "info": {"version": "1"},
    "components": {"securitySchemes": {"cleApiEnEntete": {"type": "apiKey"}}},
    "paths": {
        "/ingest/{source}/{mode}": {
            "post": {
                "description": "Dépose un lot d'objets.",
                "parameters": [
                    {"name": "source", "in": "path", "required": True},
                    {"name": "mode", "in": "path", "required": True},
                    {"name": "Idempotency-Key", "in": "header", "required": False},
                ],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {}}},
                },
                "responses": {"201": {"description": "Lot reçu."}},
            }
        },
        "/ingest/{source}/fichier": {
            "post": {
                "description": "Dépose un document.",
                "parameters": [{"name": "source", "in": "path", "required": True}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"type": "object"}},
                        "application/octet-stream": {
                            "schema": {"type": "string", "format": "binary"}
                        },
                    },
                },
                "responses": {"202": {"description": "Pris en charge."}},
            }
        },
    },
}


def _methode(mode: str, operation: str, example: Any) -> Method:
    return Method(
        source="sites",
        storage="sites",
        entry_model="pudo/site",
        mode=mode,
        path=f"/ingest/sites/{mode}",
        operation=operation,
        served=True,
        schema=MODELE,
        model_refusal=None,
        example=example,
    )


ELEMENT = _methode("element", "/ingest/{source}/{mode}", {"code": "S-1"})
TABLEAU = _methode("tableau", "/ingest/{source}/{mode}", [{"code": "S-1"}])
FICHIER = _methode("fichier", "/ingest/{source}/fichier", {"sites": [{"code": "S-1"}]})


def _corps(spec: dict[str, Any], chemin: str) -> dict[str, Any]:
    contenu = spec["paths"][chemin]["post"]["requestBody"]["content"]
    assert isinstance(contenu, dict)
    return contenu


def test_les_adresses_reelles_de_la_source_remplacent_les_gabarits() -> None:
    autre = Method(**{**vars(TABLEAU), "source": "comptes", "path": "/ingest/comptes/tableau"})

    rendu = source_spec(SPEC, [ELEMENT, TABLEAU, FICHIER, autre], "sites")

    assert rendu is not None
    assert list(rendu["paths"]) == [
        "/ingest/sites/element",
        "/ingest/sites/tableau",
        "/ingest/sites/fichier",
    ]


def test_une_source_que_la_version_servie_ne_declare_pas_n_a_pas_de_contrat() -> None:
    # None et non un document vide : un contrat sans chemin se lirait comme « cette
    # source n'expose rien », ce qui est faux — elle n'existe pas.
    assert source_spec(SPEC, [ELEMENT], "inconnue") is None


def test_ce_que_le_contrat_dit_de_lui_meme_est_conserve() -> None:
    # Recopier une description ici en aurait fait une seconde vérité : c'est le contrat
    # publié qui porte l'authentification et les garanties.
    rendu = source_spec(SPEC, [ELEMENT], "sites")

    assert rendu is not None
    assert rendu["info"] == SPEC["info"]
    assert rendu["components"] == SPEC["components"]


def test_les_parametres_de_chemin_disparaissent_de_l_adresse_concrete() -> None:
    rendu = source_spec(SPEC, [TABLEAU], "sites")

    assert rendu is not None
    parametres = rendu["paths"]["/ingest/sites/tableau"]["post"]["parameters"]
    # L'en-tête reste : il se présente toujours. Un client engendré demanderait sinon une
    # valeur pour un segment déjà écrit dans l'adresse.
    assert [p["name"] for p in parametres] == ["Idempotency-Key"]


def test_le_depot_d_un_objet_annonce_le_modele_de_l_entree() -> None:
    rendu = source_spec(SPEC, [ELEMENT], "sites")

    assert rendu is not None
    media = _corps(rendu, "/ingest/sites/element")["application/json"]
    assert media["schema"] == MODELE
    assert media["example"] == {"code": "S-1"}


def test_le_depot_d_un_lot_annonce_un_tableau_du_modele() -> None:
    rendu = source_spec(SPEC, [TABLEAU], "sites")

    assert rendu is not None
    assert _corps(rendu, "/ingest/sites/tableau")["application/json"]["schema"] == {
        "type": "array",
        "items": MODELE,
    }


def test_le_mode_fichier_garde_le_schema_du_contrat() -> None:
    # Le document a son découpage, et le modèle décrit ce qu'on trouve dedans. L'annoncer
    # comme corps serait faux — et un contrat faux coûte plus cher qu'un contrat vague.
    rendu = source_spec(SPEC, [FICHIER], "sites")

    assert rendu is not None
    contenu = _corps(rendu, "/ingest/sites/fichier")
    assert contenu["application/json"]["schema"] == {"type": "object"}
    assert contenu["application/json"]["example"] == {"sites": [{"code": "S-1"}]}
    # Le dépôt d'un document binaire reste intact.
    assert contenu["application/octet-stream"]["schema"] == {
        "type": "string",
        "format": "binary",
    }


def test_une_methode_sans_schema_ni_exemple_garde_le_corps_du_contrat() -> None:
    # Modèle illisible : on ne remplace rien plutôt que d'annoncer un corps inventé.
    muette = Method(**{**vars(ELEMENT), "schema": None, "example": None})

    rendu = source_spec(SPEC, [muette], "sites")

    assert rendu is not None
    assert _corps(rendu, "/ingest/sites/element")["application/json"] == {"schema": {}}
