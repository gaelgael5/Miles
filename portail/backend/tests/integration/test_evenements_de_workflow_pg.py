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
import yaml
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


async def _create(forge: Forge, **override: Any) -> httpx.Response:
    """Le geste du 19/11/2026 : créer l'event, son payload étant créé avec lui."""
    body: dict[str, Any] = {
        "scope": "shared",
        "label": "Colis livré",
        "slug": "colis_livre",
    } | override
    return await forge.client.post(f"{ROUTE}/declarations", json=body, timeout=120)


async def test_une_declaration_est_ecrite_dans_un_artefact_que_le_moteur_relit(
    forge: Forge,
) -> None:
    await _model(forge, "demande", DEMANDE)

    # Une clé du modèle puis une du socle : `Tracking`, écrit ici jusqu'au 15/11/2026,
    # n'était ni l'un ni l'autre, et la déclaration était refusée à bon droit
    # (`cle_d_unicite_inconnue`) — le test datait d'avant cette règle.
    declared = await _declare(forge, unique=["Montant", "ExternalId"])
    assert declared.status_code == 201, declared.text
    assert declared.json() == {
        "scope": "shared",
        "name": "demande_soumise",
        "label": "Demande soumise",
        "model": "shared/models/demande.yaml",
        "model_scope": "shared",
        "model_name": "demande",
        "unique": ["Montant", "ExternalId"],
        "model_missing": False,
        "parents": [],
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
    # Ni l'ordre alphabétique ni son inverse : un tri dans un sens ou dans l'autre rougit.
    declared = await _declare(forge, unique=["Montant", "Name", "ExternalId"])
    # Sans cette ligne, une déclaration REFUSÉE se lisait plus bas en « 404 inconnu », un
    # échec qui n'accusait pas sa cause — mesuré sur la campagne du 15/11/2026.
    assert declared.status_code == 201, declared.text

    relu = await forge.client.get(f"{ROUTE}/shared/demande_soumise", timeout=120)

    assert relu.status_code == 200, relu.text
    assert relu.json()["unique"] == ["Montant", "Name", "ExternalId"]


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

    assert [m["name"] for m in modeles.json()["models"]] == ["demande"]


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


async def test_la_liste_rend_chaque_perimetre_avec_son_artefact_et_ses_types(
    forge: Forge,
) -> None:
    """Deux périmètres, dont un SANS artefact : c'est l'arbre que le bloc Events déplie.

    Un domaine qui n'apparaîtrait qu'une fois son premier type déclaré serait introuvable
    pour le déclarer (story `8a9ff6bc`, critères 1 et 6).
    """
    await add_domain(forge, "achats")
    await _model(forge, "demande", DEMANDE)
    await _declare(forge, unique=["Montant"])

    listed = await forge.client.get(ROUTE, timeout=120)

    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {
            "scope": "shared",
            "path": ARTEFACT,
            "types": [
                {
                    "scope": "shared",
                    "name": "demande_soumise",
                    "label": "Demande soumise",
                    "model": "shared/models/demande.yaml",
                    "model_scope": "shared",
                    "model_name": "demande",
                    "unique": ["Montant"],
                    "model_missing": False,
                }
            ],
            "problems": [],
        },
        # Aucun type, et AUCUN manquement : « rien à lire » et « illisible » sont deux
        # états que l'écran doit distinguer, donc la réponse les distingue.
        {"scope": "achats", "path": "domains/achats/achats.wf", "types": [], "problems": []},
    ]


async def test_un_perimetre_illisible_n_arrete_que_lui_et_nomme_son_fichier(
    forge: Forge,
) -> None:
    """Critères 5 et 7 : un périmètre cassé ne noircit pas tout le bloc.

    Semé hors de Miles : par ses propres gestes, Miles n'écrit jamais un artefact qu'il
    ne sait pas relire. Le périmètre transverse, lui, reste lu — et c'est tout l'objet.
    """
    await add_domain(forge, "achats")
    await _model(forge, "demande", DEMANDE)
    await _declare(forge)
    await forge.seed({"domains/achats/achats.wf": "FRAGMENT NAME achats\nDEFINE EVENT ;\n"})

    listed = await forge.client.get(ROUTE, timeout=120)

    rendu = {p["scope"]: p for p in listed.json()}
    assert [d["name"] for d in rendu["shared"]["types"]] == ["demande_soumise"]
    assert rendu["achats"]["types"] == []
    assert rendu["achats"]["path"] == "domains/achats/achats.wf"
    # Les positions sont celles du MOTEUR : l'écran renvoie à la ligne fautive plutôt
    # qu'à « le fichier est invalide ».
    assert [p["line"] for p in rendu["achats"]["problems"]] == [2]


# Un artefact qui porte les CINQ sortes de déclarations qu'un fragment admet. Le portail
# n'en écrit qu'une ; les quatre autres arrivent par un humain, un agent ou un push direct,
# et il ne doit pas les détruire (bug `ff8779c6`).
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
# Ce que le portail n'écrit pas, et qui doit traverser chaque geste À L'OCTET PRÈS.
GARDEES = (
    "DESCRIPTION 'Référentiel transverse'",
    "DEFINE CONST Seuil 12 'Seuil de poids';",
    "DEFINE RULE estGrand (INTEGER poids) 'Est grand' AS @regles.grand;",
    "DEFINE ACTION notifier (TEXT destinataire) 'Notifier';",
    "DEFINE ARTIFACT Corps 'Corps HTTP' USING @scripts.corps;",
)


async def _relu_par_le_moteur(forge: Forge) -> str:
    """L'artefact tel qu'il est dans le dépôt, relu par le PARSEUR DU MOTEUR.

    Pas une comparaison de chaînes seule (critère 7) : le consommateur de ce fichier
    n'est pas Miles, et un texte qui « contient les bonnes lignes » peut très bien ne
    plus se charger.
    """
    written = await forge.file(ARTEFACT)
    assert written is not None, "l'artefact doit rester dans le dépôt"
    script = WorkflowScriptParser.parse_string(written, ARTEFACT)
    assert [(e.line, e.message) for e in script.errors] == [], written
    assert script.is_fragment
    return written


async def _avec_les_cinq_sortes(forge: Forge) -> None:
    await _model(forge, "demande", DEMANDE)
    await forge.seed({ARTEFACT: CINQ_SORTES})


async def test_declarer_un_type_garde_les_regles_actions_artefacts_et_constantes(
    forge: Forge,
) -> None:
    await _avec_les_cinq_sortes(forge)

    declared = await _declare(forge, slug="demande_recue", label="Demande reçue")

    assert declared.status_code == 201, declared.text
    written = await _relu_par_le_moteur(forge)
    for gardee in GARDEES:
        assert gardee in written, f"déclaration perdue : {gardee}"
    assert "DEFINE EVENT demande_recue 'Demande reçue'" in written


async def test_modifier_un_type_garde_les_quatre_autres_sortes(forge: Forge) -> None:
    await _avec_les_cinq_sortes(forge)

    changed = await forge.client.put(
        f"{ROUTE}/shared/demande_soumise",
        json={
            "label": "Demande reçue",
            "model_scope": "shared",
            "model_name": "demande",
            "unique": ["Montant"],
        },
        timeout=120,
    )

    assert changed.status_code == 200, changed.text
    written = await _relu_par_le_moteur(forge)
    for gardee in GARDEES:
        assert gardee in written, f"déclaration perdue : {gardee}"
    assert "DEFINE EVENT demande_soumise 'Demande reçue'" in written
    assert "UNIQUE (Montant)" in written


async def test_supprimer_le_dernier_type_GARDE_le_fichier_quand_une_regle_y_reste(
    forge: Forge,
) -> None:
    """Critère 3 : le fichier ne se retire que s'il ne reste RIEN à déclarer.

    Aujourd'hui il est supprimé dès qu'il n'y a plus de type d'event — ce qui emporte la
    règle, l'action, l'artefact et la constante avec lui.
    """
    await _avec_les_cinq_sortes(forge)

    removed = await forge.client.delete(f"{ROUTE}/shared/demande_soumise", timeout=120)

    assert removed.status_code == 204, removed.text
    written = await _relu_par_le_moteur(forge)
    for gardee in GARDEES:
        assert gardee in written, f"déclaration perdue : {gardee}"
    assert "DEFINE EVENT" not in written


async def test_deux_gestes_de_suite_ne_font_pas_danser_le_fichier(forge: Forge) -> None:
    """Critère 5 : l'ordre des déclarations conservées est stable d'un geste à l'autre.

    Sans cette garde, chaque geste pourrait réécrire le fichier dans un autre ordre, et
    l'historique git deviendrait illisible pour un changement d'un libellé.

    Celui-ci ne DISCRIMINE PAS le bug `ff8779c6`, et c'est mesuré : il était déjà vert
    sur le code fauté, où le fichier entier était rendu depuis la liste des types — donc
    déterministe. Il garde le nouveau code, où un découpage maladroit pourrait, lui,
    déplacer les lignes. Les trois tests au-dessus, eux, ont bien été vus rouges.
    """
    await _avec_les_cinq_sortes(forge)
    await _declare(forge, slug="demande_recue", label="Demande reçue")
    apres_un = await _relu_par_le_moteur(forge)

    await forge.client.put(
        f"{ROUTE}/shared/demande_recue",
        json={
            "label": "Demande reçue par le comptoir",
            "model_scope": "shared",
            "model_name": "demande",
            "unique": [],
        },
        timeout=120,
    )

    apres_deux = await _relu_par_le_moteur(forge)
    # Tout ce qui n'est pas la ligne modifiée est identique, ligne pour ligne.
    changees = [
        (une, deux)
        for une, deux in zip(apres_un.splitlines(), apres_deux.splitlines(), strict=True)
        if une != deux
    ]
    assert len(changees) == 1, changees
    assert "Demande reçue par le comptoir" in changees[0][1]


# --- L'HÉRITAGE entre types d'event (story 6064ce93) -------------------------------------
#
# Ce que ces tests tiennent et qu'aucun test unitaire ne tient : que les DEUX fichiers d'une
# création arrivent dans le dépôt en UN commit, que l'artefact reste relisible par le moteur,
# et qu'un cycle refusé ne laisse rien derrière lui.


async def test_creer_un_event_ecrit_son_payload_ET_sa_declaration_en_un_seul_commit(
    forge: Forge,
) -> None:
    avant = await forge.commits()

    created = await _create(forge)

    assert created.status_code == 201, created.text
    assert created.json()["model"] == "shared/models/colis_livre.yaml"
    # Aucun parent : c'est l'event de base, dont le moteur applique la racine d'office —
    # il n'y a donc RIEN à écrire dans le fichier (décision 2 du 22/11/2026).
    assert created.json()["parents"] == []
    model = await forge.file("shared/models/colis_livre.yaml")
    assert model is not None
    assert yaml.safe_load(model)["$id"] == "miles:/shared/colis_livre"
    assert "allOf" not in yaml.safe_load(model)
    # L'artefact déclare l'event, et c'est le MOTEUR qui le relit.
    artefact = await forge.file(ARTEFACT)
    assert artefact is not None
    script = WorkflowScriptParser.parse_string(artefact, ARTEFACT)
    assert [(e.line, e.message) for e in script.errors] == []
    assert "AS @shared.colis_livre" in artefact
    # UN commit pour les deux fichiers : deux laisseraient, si le second échouait, un
    # modèle que rien ne déclare.
    assert await forge.commits() == avant + 1


async def test_un_event_cree_sur_un_autre_HERITE_de_son_payload(forge: Forge) -> None:
    await _create(forge, slug="colis_recu", label="Colis reçu")

    created = await _create(forge, parent_scope="shared", parent_name="colis_recu")

    assert created.status_code == 201, created.text
    assert created.json()["parents"] == ["shared/models/colis_recu.yaml"]
    model = yaml.safe_load(await forge.file("shared/models/colis_livre.yaml") or "")
    # LA forme standard, et rien d'autre : aucun champ du parent recopié, aucun fichier de
    # métadonnées, le lien EST le `$ref`.
    assert model["allOf"] == [{"$ref": "miles:/shared/colis_recu"}]
    assert model["properties"] == {}


async def test_l_heritage_se_redirige_puis_revient_a_l_event_de_base(forge: Forge) -> None:
    await _create(forge, slug="colis_recu", label="Colis reçu")
    await _create(forge, slug="colis_trie", label="Colis trié")
    await _create(forge, parent_scope="shared", parent_name="colis_recu")

    redirected = await forge.client.put(
        f"{ROUTE}/shared/colis_livre/parent",
        json={"parent_scope": "shared", "parent_name": "colis_trie"},
        timeout=120,
    )

    assert redirected.status_code == 200, redirected.text
    assert redirected.json()["parents"] == ["shared/models/colis_trie.yaml"]
    model = yaml.safe_load(await forge.file("shared/models/colis_livre.yaml") or "")
    assert model["allOf"] == [{"$ref": "miles:/shared/colis_trie"}]

    # Un corps vide ramène à l'event de base, et le renvoi disparaît du fichier.
    back = await forge.client.put(f"{ROUTE}/shared/colis_livre/parent", json={}, timeout=120)

    assert back.status_code == 200, back.text
    assert back.json()["parents"] == []
    assert "allOf" not in yaml.safe_load(await forge.file("shared/models/colis_livre.yaml") or "")
    # Et l'artefact du périmètre n'a pas bougé : une redirection ne touche que le modèle.
    assert "AS @shared.colis_livre" in (await forge.file(ARTEFACT) or "")


async def test_un_cycle_est_refuse_et_RIEN_n_est_ecrit(forge: Forge) -> None:
    """Le cas qui, sans garde, ne rend pas un refus : il fait tomber le validateur.

    Mesuré le 22/11/2026 — un schéma qui se désigne lui-même part en `RecursionError`.
    """
    await _create(forge, slug="colis_recu", label="Colis reçu")
    await _create(forge, parent_scope="shared", parent_name="colis_recu")
    avant = await forge.file("shared/models/colis_recu.yaml")

    refused = await forge.client.put(
        f"{ROUTE}/shared/colis_recu/parent",
        json={"parent_scope": "shared", "parent_name": "colis_livre"},
        timeout=120,
    )

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "declaration_non_conforme"
    assert [(p["path"], p["code"]) for p in detail["problems"]] == [("allOf", "heritage_recursif")]
    # Le FICHIER après le refus, et non le code de retour : c'est lui qui dit si quelque
    # chose a été écrit.
    assert await forge.file("shared/models/colis_recu.yaml") == avant


async def test_un_event_ne_peut_pas_heriter_de_lui_meme(forge: Forge) -> None:
    await _create(forge)

    refused = await forge.client.put(
        f"{ROUTE}/shared/colis_livre/parent",
        json={"parent_scope": "shared", "parent_name": "colis_livre"},
        timeout=120,
    )

    assert refused.status_code == 422, refused.text
    assert [p["code"] for p in refused.json()["detail"]["problems"]] == ["heritage_recursif"]


async def test_une_cle_d_unicite_sur_une_propriete_HERITEE_est_admise(forge: Forge) -> None:
    """La conséquence directe de l'héritage : le moteur valide le schéma COMPOSÉ.

    Sans la lecture de l'ascendance, le portail refuserait `UNIQUE (Montant)` en nommant
    une propriété qui existe — celle que le parent apporte.
    """
    await _model(forge, "demande", DEMANDE)
    await _declare(forge, slug="demande_soumise", model_name="demande")

    created = await _create(
        forge, parent_scope="shared", parent_name="demande_soumise", unique=["Montant"]
    )

    assert created.status_code == 201, created.text
    assert created.json()["unique"] == ["Montant"]
    # Et la branche reste gelable : un payload hérité sans propriété propre est légitime.
    freezable = await forge.client.get(FREEZABLE, timeout=120)
    assert freezable.status_code == 200, freezable.text
    assert freezable.json()["reports"] == []


async def test_heriter_d_un_event_d_un_AUTRE_domaine_est_refuse(forge: Forge) -> None:
    """Un périmètre transverse qui hériterait d'un domaine cesserait d'être transverse, et
    le moteur chargerait un schéma que les autres domaines ne voient pas."""
    await add_domain(forge, "livraison")
    await _create(forge, scope="livraison", slug="colis_trie", label="Colis trié")

    refused = await _create(forge, parent_scope="livraison", parent_name="colis_trie")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "portee_du_modele"


async def test_un_parent_inconnu_est_refuse_sans_rien_ecrire(forge: Forge) -> None:
    refused = await _create(forge, parent_scope="shared", parent_name="jamais_declare")

    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "evenement_inconnu"
    assert await forge.remote_file("shared/models/colis_livre.yaml") is None
