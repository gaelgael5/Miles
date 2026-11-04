"""Essayer une méthode d'ingestion depuis l'écran, sur une VRAIE base (ticket a78551e5).

Ce qui ne s'éprouve QUE là, et qu'aucune doublure ne dit :

- que le back-office frappe sa propre route par le **vrai** chemin — portillon, routage,
  vérification de l'empreinte, octrois relus contre la version servie — et qu'un objet
  arrive bien dans la table du storage ;
- que la clé est **émise une fois** et retrouvée, parce que le magasin de secrets chiffre
  et déchiffre pour de vrai ;
- que **sa valeur ne fuit nulle part** : ni dans une réponse, ni dans la table des
  ingestions, ni dans le journal d'events, ni dans les journaux du service ;
- que l'identité de l'administrateur est **inscrite** à côté du dépôt, qui est attribué à
  une clé ;
- qu'une clé **révoquée** est dite, et qu'une réémission explicite remet la page en marche.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.apikeys.self_key import SELF_KEY_LABEL, SELF_KEY_SLUG, SELF_KEY_TYPE
from environnement.ingestion.api_trial import REFUSAL_KEY_REVOKED
from environnement.ingestion.trial import TRIAL_EVENT
from tests.integration.bundles import fabrique_import, fabrique_parametrage
from tests.integration.environnement_stack import ADMIN_USERNAME, EnvironnementStack, open_stack
from tests.integration.versions import ordonne, sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
TABLEAU = f"/api/ingestion/try/{SOURCE}/tableau"
LOT = [{"code": "M-1", "nom": "Gare du Nord", "ville": "Paris", "postes": 3}]


async def _methodes(stack: EnvironnementStack) -> dict[tuple[str, str], Any]:
    lues = await stack.client.get("/api/ingestion/methods")
    assert lues.status_code == 200, lues.text
    return {(m["source"], m["mode"]): m for m in lues.json()["methods"]}


async def _essaie(stack: EnvironnementStack, corps: Any, chemin: str = TABLEAU) -> Any:
    return await stack.client.post(chemin, content=json.dumps(corps).encode())


async def _secret(stack: EnvironnementStack) -> str:
    """La valeur rangée de la clé du back-office. Pour la CHERCHER là où elle ne doit pas
    être — c'est le seul usage légitime de sa lecture dans un test."""
    range = await stack.ingestion_self_key.secrets.resolve_secret(SELF_KEY_SLUG, SELF_KEY_TYPE)
    return range.reveal()


async def test_un_essai_depose_pour_de_vrai_et_rend_la_reponse_du_point_d_entree(
    blank_db: str, tmp_path: Path
) -> None:
    """Le cas nominal, et il prouve la chaîne entière : le corps d'exemple que la page
    propose, déposé tel quel, est accepté — donc le modèle d'entrée montré est bien celui
    dont la chaîne part."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        gabarit = (await _methodes(stack))[(SOURCE, "tableau")]["example"]

        recu = await _essaie(stack, gabarit)

        assert recu.status_code == 200, recu.text
        # Le statut du DÉPÔT, porté par une réponse d'écran qui, elle, a réussi.
        assert recu.json()["status"] == 201
        rapport = recu.json()["body"]["report"]
        assert (rapport["received"], rapport["written"]) == (1, 1)
        # Et l'objet est en base, sous la forme du modèle cible : la chaîne a tourné.
        ligne = await stack.pool.fetchrow("SELECT cle, objet::text AS objet FROM pudo.magasins")
        assert json.loads(ligne["objet"])["Libelle"] == "nom"


async def test_la_cle_du_back_office_est_emise_UNE_fois_et_retrouvee(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux essais ne créent pas deux clés : la valeur est relue du magasin."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        premier = await _essaie(stack, LOT)
        second = await _essaie(stack, LOT)

        assert (premier.json()["status"], second.json()["status"]) == (201, 201)
        combien = await stack.pool.fetchval(
            "SELECT count(*) FROM api_keys WHERE label = $1", SELF_KEY_LABEL
        )
        assert combien == 1
        # Octroyée sur la source déclarée : c'est ce qui la fait passer le fail closed.
        octrois = await stack.pool.fetchval(
            "SELECT array_agg(g.source) FROM api_key_grants g"
            " JOIN api_keys k ON k.id = g.key_id WHERE k.label = $1",
            SELF_KEY_LABEL,
        )
        assert list(octrois) == [SOURCE]


async def test_la_valeur_de_la_cle_ne_fuit_NULLE_PART(
    blank_db: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Le critère de sécurité du ticket, et il se cherche là où ça fuite d'habitude.

    Quatre endroits, et chacun a déjà fait fuiter un secret dans un projet : la réponse
    HTTP, la table qui garde la trace du dépôt, le journal d'events — lu bien plus
    largement que la table des secrets — et la sortie du service, qui part vers
    l'agrégateur de journaux avec une rétention qui n'est pas la nôtre.
    """
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        recu = await _essaie(stack, LOT)
        valeur = await _secret(stack)

        assert recu.status_code == 200
        assert valeur not in recu.text
        # La page des clés non plus : elle n'en montre que le préfixe.
        assert valeur not in (await stack.client.get("/api/api-keys")).text
        for table, colonne in (("ingestions", "raw::text"), ("events", "properties::text")):
            tout = await stack.pool.fetchval(
                f"SELECT coalesce(string_agg({colonne}, ' '), '') FROM {table}"  # noqa: S608
            )
            assert valeur not in tout, table
        sorties = capsys.readouterr()
        assert valeur not in sorties.out + sorties.err


async def test_un_essai_inscrit_l_identite_de_l_administrateur_qui_l_a_lance(
    blank_db: str, tmp_path: Path
) -> None:
    """Le journal attribue un dépôt à une CLÉ, jamais à une personne — c'est voulu. Sans
    cet event, un essai depuis l'écran serait indiscernable du dépôt d'un partenaire."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        recu = await _essaie(stack, LOT)

        ingestion = recu.json()["body"]["id"]
        event = await stack.pool.fetchrow(
            "SELECT e.author_directory, e.author_subject, e.properties::text AS p"
            " FROM events e JOIN event_objects o"
            " ON o.event_id = e.id AND o.written_at = e.written_at"
            " WHERE e.type = $1 AND o.object_id = $2",
            TRIAL_EVENT,
            ingestion,
        )
        assert event is not None
        assert event["author_subject"] == ADMIN_USERNAME
        assert json.loads(event["p"])["source"] == SOURCE
        # Et le dépôt lui-même reste attribué à la clé du back-office : c'est ce que le
        # journal des appels affiche, et il doit dire d'où vient le dépôt.
        appel = await stack.pool.fetchrow(
            "SELECT key_label FROM ingestions WHERE id = $1", ingestion
        )
        assert appel["key_label"] == SELF_KEY_LABEL


async def test_un_refus_du_point_d_entree_n_inscrit_aucun_essai(
    blank_db: str, tmp_path: Path
) -> None:
    """Rien n'a été créé : il n'y a aucun dépôt à rattacher, et inventer un event
    laisserait croire qu'un lot est arrivé."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        recu = await _essaie(stack, {"pas": "un tableau"})

        assert recu.json()["status"] == 400
        assert recu.json()["body"]["detail"]["code"] == "tableau_attendu"
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0
        essais = await stack.pool.fetchval(
            "SELECT count(*) FROM events WHERE type = $1", TRIAL_EVENT
        )
        assert essais == 0


async def test_une_cle_revoquee_est_DITE_puis_une_reemission_explicite_remet_en_marche(
    blank_db: str, tmp_path: Path
) -> None:
    """La révocation est un geste délibéré : reprise en silence, elle serait annulée."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        assert (await _essaie(stack, LOT)).json()["status"] == 201
        cle = await stack.pool.fetchval("SELECT id FROM api_keys WHERE label = $1", SELF_KEY_LABEL)
        await stack.client.post(f"/api/api-keys/{cle}/revoke")

        refus = await _essaie(stack, LOT)
        reemise = await stack.client.post("/api/ingestion/self-key")
        repris = await _essaie(stack, LOT)

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"]["code"] == REFUSAL_KEY_REVOKED
        assert reemise.status_code == 201, reemise.text
        assert repris.json()["status"] == 201
        # L'ancienne reste visible, avec les dépôts qu'elle a portés : effacer son
        # histoire ferait perdre la trace de ce qu'elle a écrit.
        restantes = await stack.pool.fetch(
            "SELECT revoked_at FROM api_keys WHERE label = $1 ORDER BY created_at", SELF_KEY_LABEL
        )
        assert [row["revoked_at"] is None for row in restantes] == [False, True]


async def test_un_essai_sur_une_source_RETIREE_de_la_version_servie_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Éprouvé en faisant SERVIR une version qui retire la source : une version qui
    ajoute ne prouverait rien. C'est le même refus qu'un partenaire reçoit."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        chemin = "/api/ingestion/try/sites-pudo/element"
        assert (await _essaie(stack, {"Id": "S-1"}, chemin)).json()["status"] == 201

        await ordonne(stack, double, versions[3])
        ferme = await _essaie(stack, {"Id": "S-2"}, chemin)

        # 401, comme pour un tiers : l'octroi vit en base, la source vit dans git, et
        # c'est la relecture à chaque appel qui ferme la porte.
        assert ferme.json()["status"] == 401
        assert ferme.json()["body"]["detail"]["code"] == "authentification_requise"


async def test_les_methodes_portent_le_schema_du_modele_d_entree_et_la_troisieme_sans_corps(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        lues = await _methodes(stack)

        tableau = lues[(SOURCE, "tableau")]
        assert tableau["entry_model"] == "pudo/magasin-import"
        assert tableau["storage"] == "magasins"
        assert sorted(tableau["request_schema"]["properties"]) == ["code", "nom", "postes", "ville"]
        # Le gabarit du mode `tableau` est un TABLEAU : un objet se ferait refuser pour
        # « tableau attendu », et on chercherait l'erreur dans le modèle.
        assert isinstance(tableau["example"], list)
        assert lues[(SOURCE, "element")]["example"] == tableau["example"][0]
        assert ("magasins-import", "fichier") not in lues


async def test_un_modele_d_entree_absent_de_la_version_servie_est_NOMME(
    blank_db: str, tmp_path: Path
) -> None:
    """Et non remplacé par un corps vide, qui se lirait « cette méthode n'attend rien »."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        # La v1 déclare `comptes-pudo` sur `pudo/accounts`, puis on retire le fichier du
        # modèle de l'arbre servi : c'est l'état d'un paramétrage incomplet.
        (tmp_path / "parametrage" / "domains" / "pudo" / "messages" / "accounts.yaml").unlink()

        lues = await _methodes(stack)

        comptes = lues[("comptes-pudo", "tableau")]
        assert comptes["model_refusal"] == "modele_absent"
        assert comptes["request_schema"] is None
        assert comptes["example"] is None


async def test_le_contrat_servi_est_EXACTEMENT_celui_qui_est_publie(
    blank_db: str, tmp_path: Path
) -> None:
    """Une seule vérité sur la forme : la route rend ce que le fichier versionné porte.

    Comparé au fichier du dépôt, et non à une régénération : c'est le fichier qu'un
    partenaire lit, et c'est lui qui doit correspondre à ce que l'écran montre.
    """
    from environnement.published_contracts import CONTRACTS_DIR, OPENAPI_FILE

    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        servi = await stack.client.get("/api/ingestion/contract")

        assert servi.status_code == 200, servi.text
        publie = json.loads((CONTRACTS_DIR / OPENAPI_FILE).read_text(encoding="utf-8"))
        assert servi.json() == publie


async def test_les_routes_de_la_page_sont_fermees_sans_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Fail closed : la surface d'administration n'est pas ouverte à l'anonyme, et une
    route qui déclenche un DÉPÔT encore moins."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        for chemin in ("/api/ingestion/methods", "/api/ingestion/contract"):
            assert (await stack.anonymous().get(chemin)).status_code == 401, chemin
        for chemin in ("/api/ingestion/self-key", TABLEAU):
            refus = await stack.anonymous().post(chemin, content=b"[]")
            assert refus.status_code == 401, chemin
