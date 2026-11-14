"""Le référentiel des types d'event, de bout en bout : la route, le dépôt, et le MOTEUR.

Ce que ces tests tiennent, et qu'aucun test unitaire ne peut tenir : qu'une déclaration
faite par l'écran arrive dans le dépôt sous la forme que le PARSEUR DU MOTEUR relit, que
les clés d'unicité en reviennent dans l'ordre saisi, qu'un modèle désigné par un
`DEFINE EVENT` reste un modèle ordinaire — storages et sources peuvent le désigner — et
qu'une version de branche valide tout cela.

Le consommateur de l'artefact n'est pas Miles : c'est pourquoi chaque écriture est relue
ici par `urban_workflow`, et pas seulement comparée à un texte attendu.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.datamodels.schema import normalized as normalized_model
from tests.integration.test_domains_pg import add_domain
from tests.integration.work_stack import Forge, open_work_forge

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/workflow-events"
MODELES = "/api/workspaces/retrait/data-models"
FREEZABLE = "/api/workspaces/retrait/versions/freezable"
ARTEFACT = "shared/shared.wf"

DEMANDE = normalized_model(
    "title: Demande\ntype: object\nproperties:\n  Montant: {type: number}\n",
    "shared",
    "demande",
)
# Un modèle SANS propriété métier : légitime pour un type d'event, qui peut n'apporter que
# le socle commun du moteur.
PING = normalized_model("title: Ping\ntype: object\nproperties: {}\n", "shared", "ping")


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    async with open_work_forge(blank_db, tmp_path) as opened:
        yield opened


async def _model(forge: Forge, name: str, content: str, scope: str = "shared") -> None:
    written = await forge.client.post(
        MODELES, json={"scope": scope, "name": name, "content": content}, timeout=120
    )
    assert written.status_code in (200, 201), written.text


async def _declare(forge: Forge, **override: Any) -> httpx.Response:
    body = {
        "scope": "shared",
        "label": "Demande soumise",
        "slug": "demande_soumise",
        "model_scope": "shared",
        "model_name": "demande",
    } | override
    return await forge.client.post(f"{ROUTE}/declarations", json=body, timeout=120)


async def test_une_declaration_est_ecrite_dans_un_artefact_que_le_moteur_relit(
    forge: Forge,
) -> None:
    await _model(forge, "demande", DEMANDE)

    declared = await _declare(forge, unique=["Tracking", "ExternalId"])
    assert declared.status_code == 201, declared.text
    assert declared.json() == {
        "scope": "shared",
        "name": "demande_soumise",
        "label": "Demande soumise",
        "model": "shared/models/demande.yaml",
        "model_scope": "shared",
        "model_name": "demande",
        "unique": ["Tracking", "ExternalId"],
        "model_missing": False,
    }

    written = await forge.file(ARTEFACT)
    assert written is not None, "l'artefact du périmètre doit être écrit"
    # LE contrôle de ce fichier : le moteur, pas une comparaison de texte.
    script = WorkflowScriptParser.parse_string(written, ARTEFACT)
    assert [(e.line, e.message) for e in script.errors] == []
    assert script.is_fragment
    assert "AS @shared.demande" in written


async def test_l_ordre_des_cles_d_unicite_est_conserve_a_la_relecture(forge: Forge) -> None:
    """L'ordre est une DONNÉE : le moteur dérive le hash d'anti-doublon par concaténation
    (`compute_dedup_hash`), donc deux ordres donnent deux anti-doublons. Un tri à
    l'écriture ou à la relecture changerait le dédoublonnage d'un référentiel en service.
    """
    await _model(forge, "demande", DEMANDE)
    await _declare(forge, unique=["Tracking", "ExternalId", "Montant"])

    relu = await forge.client.get(f"{ROUTE}/shared/demande_soumise", timeout=120)

    assert relu.status_code == 200, relu.text
    assert relu.json()["unique"] == ["Tracking", "ExternalId", "Montant"]


async def test_un_type_de_domaine_vit_dans_l_artefact_de_son_domaine(forge: Forge) -> None:
    await add_domain(forge, "achats")
    await _model(
        forge,
        "commande",
        normalized_model(
            "title: C\ntype: object\nproperties:\n  Ref: {type: string}\n", "achats", "commande"
        ),
        scope="achats",
    )

    declared = await _declare(
        forge,
        scope="achats",
        slug="validation",
        label="Validation",
        model_scope="achats",
        model_name="commande",
    )

    assert declared.status_code == 201, declared.text
    assert await forge.file("domains/achats/achats.wf") is not None
    assert await forge.file(ARTEFACT) is None, "le périmètre transverse n'a rien à déclarer"


async def test_supprimer_le_dernier_type_RETIRE_l_artefact_au_lieu_de_le_vider(
    forge: Forge,
) -> None:
    """Un FRAGMENT sans déclaration est une erreur de syntaxe pour le moteur (mesuré :
    « mismatched input '<EOF>' expecting 'DEFINE' »). Laisser le fichier vide ferait
    échouer le chargement de TOUT le répertoire, pour un périmètre devenu vide."""
    await _model(forge, "demande", DEMANDE)
    await _declare(forge)

    removed = await forge.client.delete(f"{ROUTE}/shared/demande_soumise", timeout=120)

    assert removed.status_code == 204, removed.text
    assert await forge.file(ARTEFACT) is None


async def test_un_modele_ferme_est_refuse_a_la_declaration_en_NOMMANT_la_raison(
    forge: Forge,
) -> None:
    """Le refus que le moteur aurait prononcé à l'exécution, prononcé à la déclaration."""
    await _model(
        forge,
        "ferme",
        normalized_model(
            "title: F\ntype: object\nadditionalProperties: false\n"
            "properties:\n  M: {type: number}\n",
            "shared",
            "ferme",
        ),
    )

    refused = await _declare(forge, model_name="ferme")

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "declaration_non_conforme"
    assert ("additionalProperties", "schema_ferme") in [
        (p["path"], p["code"]) for p in detail["problems"]
    ]


async def test_un_modele_qui_redeclare_une_propriete_du_socle_est_refuse(forge: Forge) -> None:
    await _model(
        forge,
        "double",
        normalized_model(
            "title: D\ntype: object\nproperties:\n  ExternalId: {type: integer}\n",
            "shared",
            "double",
        ),
    )

    refused = await _declare(forge, model_name="double")

    assert refused.status_code == 422, refused.text
    assert [p["code"] for p in refused.json()["detail"]["problems"]] == ["propriete_du_socle"]


async def test_une_cle_d_unicite_qui_ne_designe_rien_est_refusee(forge: Forge) -> None:
    await _model(forge, "demande", DEMANDE)

    refused = await _declare(forge, unique=["Inexistant"])

    assert refused.status_code == 422, refused.text
    assert [p["code"] for p in refused.json()["detail"]["problems"]] == ["cle_d_unicite_inconnue"]


async def test_un_modele_absent_est_refuse_en_nommant_son_chemin(forge: Forge) -> None:
    refused = await _declare(forge)

    assert refused.status_code == 422, refused.text
    problems = refused.json()["detail"]["problems"]
    assert [(p["code"], p["detail"]) for p in problems] == [
        ("modele_inconnu", "shared/models/demande.yaml")
    ]


async def test_un_nom_que_le_DSL_refuserait_est_refuse_a_la_declaration(forge: Forge) -> None:
    await _model(forge, "demande", DEMANDE)

    refused = await _declare(forge, slug="demande-soumise")

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == {"field": "name"}


async def test_un_modele_a_tiret_ne_peut_pas_devenir_un_type_d_event(forge: Forge) -> None:
    """Il reste un modèle utilisable par un storage ou une source : c'est le DSL qui ne
    sait pas écrire `AS @shared.mon-modele`, pas Miles qui refuse le nom."""
    await _model(
        forge,
        "mon-modele",
        normalized_model(
            "title: M\ntype: object\nproperties:\n  A: {type: string}\n", "shared", "mon-modele"
        ),
    )

    refused = await _declare(forge, model_name="mon-modele")

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == {"field": "model_non_ecrivable"}


async def test_le_socle_commun_est_servi_en_SCHEMA_depuis_le_moteur_installe(
    forge: Forge,
) -> None:
    """Un JSON Schema, pas une liste de noms : l'écran le monte dans le même éditeur
    visuel que les champs métier, verrouillé, et c'est ce qui montre la dérivation."""
    served = await forge.client.get(f"{ROUTE}/socle", timeout=120)

    assert served.status_code == 200, served.text
    socle = served.json()
    assert socle["type"] == "object"
    assert {"Name", "Uuid", "ExternalId", "CreationDate", "EventDate", "DedupKey"} <= set(
        socle["properties"]
    )
    assert socle["properties"]["IntegrationDate"]["readOnly"] is True
    assert socle["properties"]["Uuid"]["format"] == "uuid"
    assert socle["required"] == ["Name"]


async def test_le_modele_d_un_type_d_event_RESTE_dans_la_liste_des_modeles(forge: Forge) -> None:
    """La conséquence assumée du 14/11/2026, et elle se mesure : la liste séparée
    interdisait à un storage ou à une source de désigner un schéma d'event. Ce n'est plus
    le cas — c'est la déclaration, et non le rangement, qui dit ce qu'est un type d'event.
    """
    await _model(forge, "demande", DEMANDE)
    await _declare(forge)

    modeles = await forge.client.get(MODELES, timeout=120)

    assert [m["name"] for m in modeles.json()] == ["demande"]


async def test_supprimer_un_modele_qu_une_declaration_designe_est_refuse(forge: Forge) -> None:
    """Sans cette garde, la déclaration ne désignerait plus rien — et c'est la version de
    la branche qui l'aurait dit, trop tard et depuis un autre écran. Le refus nomme
    l'ARTEFACT, parce que c'est le fichier qu'il faut aller corriger."""
    await _model(forge, "demande", DEMANDE)
    await _declare(forge)

    refused = await forge.client.delete(f"{MODELES}/shared/demande", timeout=120)

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"code": "utilise", "by": [ARTEFACT]}


async def test_une_branche_qui_declare_un_type_sur_un_modele_vide_reste_gelable(
    forge: Forge,
) -> None:
    """Un modèle sans propriété est un brouillon — sauf quand un `DEFINE EVENT` le
    désigne : un type d'event peut n'apporter que le socle commun et déclencher une
    transition sur ce seul fait. Sans cette exception, déclarer un tel type bloquerait
    toute version de la branche."""
    await _model(forge, "ping", PING)
    await _declare(forge, slug="ping", label="Ping", model_name="ping")

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    assert freezable.status_code == 200, freezable.text
    assert freezable.json()["reports"] == []


async def test_un_modele_vide_que_personne_ne_declare_bloque_toujours_la_version(
    forge: Forge,
) -> None:
    # Discriminant : sans ce test, l'exception ci-dessus pourrait avoir ouvert la règle
    # pour TOUS les modèles sans que rien ne le dise.
    await _model(forge, "ping", PING)

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    rapports = {r["path"]: [p["code"] for p in r["problems"]] for r in freezable.json()["reports"]}
    assert rapports["shared/models/ping.yaml"] == ["proprietes_vides"]


async def test_un_artefact_retouche_hors_de_miles_bloque_la_version_en_le_nommant(
    forge: Forge,
) -> None:
    """La validation lit l'artefact du DÉPÔT, pas ce que Miles vient d'écrire. Un artefact
    illisible ferait échouer le chargement de tout le répertoire chez le moteur : il ne
    doit pas pouvoir entrer dans une version."""
    await forge.seed({ARTEFACT: "FRAGMENT NAME shared\nDEFINE EVENT ;\n"})

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    rapports = {r["path"]: [p["code"] for p in r["problems"]] for r in freezable.json()["reports"]}
    assert rapports[ARTEFACT] == ["artefact_illisible"]


async def test_un_artefact_qui_designe_un_modele_disparu_bloque_la_version(forge: Forge) -> None:
    await forge.seed({ARTEFACT: "FRAGMENT NAME shared\nDEFINE EVENT ping 'P' AS @shared.absent;\n"})

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    rapports = {r["path"]: [p["code"] for p in r["problems"]] for r in freezable.json()["reports"]}
    assert rapports[ARTEFACT] == ["modele_inconnu"]


async def test_un_meme_nom_declare_par_deux_perimetres_bloque_la_version(forge: Forge) -> None:
    """Mesuré : un script qui `INCLUDE` les deux artefacts ne charge pas du tout — le
    moteur lève « event 'ping' is already declared ». Aucun des deux fichiers n'est fautif
    seul, c'est leur coexistence qui l'est, et les deux sont donc rapportés."""
    await add_domain(forge, "achats")
    await forge.seed(
        {
            "shared/models/ping.yaml": PING,
            "domains/achats/models/ping.yaml": normalized_model(
                "title: P\ntype: object\nproperties:\n  A: {type: string}\n", "achats", "ping"
            ),
            ARTEFACT: "FRAGMENT NAME shared\nDEFINE EVENT ping 'P' AS @shared.ping;\n",
            "domains/achats/achats.wf": (
                "FRAGMENT NAME achats\nDEFINE EVENT ping 'P' AS @domains.achats.ping;\n"
            ),
        }
    )

    freezable = await forge.client.get(FREEZABLE, timeout=120)

    rapports = {r["path"]: [p["code"] for p in r["problems"]] for r in freezable.json()["reports"]}
    assert rapports[ARTEFACT] == ["nom_declare_deux_fois"]
    assert rapports["domains/achats/achats.wf"] == ["nom_declare_deux_fois"]


async def test_aucune_route_des_types_d_event_n_est_atteignable_sans_session(
    forge: Forge,
) -> None:
    """Fail closed : le portillon refuse, et il faut le mesurer route par route."""
    declaration = {
        "scope": "shared",
        "label": "D",
        "slug": "d",
        "model_scope": "shared",
        "model_name": "demande",
    }
    appels = (
        ("GET", ROUTE, None),
        ("GET", f"{ROUTE}/socle", None),
        ("GET", f"{ROUTE}/shared/demande_soumise", None),
        ("POST", f"{ROUTE}/declarations", declaration),
        (
            "PUT",
            f"{ROUTE}/shared/demande_soumise",
            {"label": "D", "model_scope": "shared", "model_name": "demande"},
        ),
        ("DELETE", f"{ROUTE}/shared/demande_soumise", None),
    )
    async with forge.portal.anonymous() as visiteur:
        for methode, url, body in appels:
            refused = await visiteur.request(methode, url, json=body, timeout=120)
            assert refused.status_code in (401, 403), f"{methode} {url} -> {refused.status_code}"
