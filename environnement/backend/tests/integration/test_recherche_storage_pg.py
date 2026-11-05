"""Retrouver les objets d'un storage par sa clé fonctionnelle et ses index déclarés.

« je veux egalement voir des filtres de recherche par rapport à la clef fonctionnel et aux
indexes créé dans configuration » (Gael, 02/11/2026).

Sur une vraie base, parce que c'est là que les choses se décident : qu'une comparaison
rende le bon ordre prouve que la valeur n'est pas hachée, et qu'un plan d'exécution
EMPRUNTE l'index déclaré prouve qu'on a acheté quelque chose avec ce DDL.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.keys import key_of
from tests.integration.bundles import VersionFabriquee, fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

WORKSPACE = "reseau-ferroviaire"
# Trois comptes, dont deux partagent un préfixe de téléphone : un jeu où chaque filtre
# doit DISCRIMINER. Avec des valeurs toutes différentes, un filtre faux resterait vert.
# Les dates franchissent un changement d'année et se suivent à un jour près : un tri qui
# couperait l'ISO-8601 ou le relirait en nombre les mélangerait, et le test le verrait.
OBJETS = [
    {"AccountId": "A-1", "Postes": 3, "Ouvert": "2026-01-09", "Contact": {"Phone": "0102030405"}},
    {"AccountId": "A-2", "Postes": 12, "Ouvert": "2025-12-31", "Contact": {"Phone": "0102999999"}},
    {"AccountId": "A-3", "Postes": 7, "Ouvert": "2026-01-10", "Contact": {"Phone": "0600000000"}},
]
# Les clés sont fabriquées par la FONCTION DE PRODUCTION, jamais écrites à la main : le
# jeu d'essai portait « A-1 » là où l'ingestion écrit `["A-1"]`, une forme qui n'existe
# dans aucune base. Les filtres passaient donc contre une clé inventée, et la recherche
# par clé était fausse sur la vraie stack sans qu'aucun test ne puisse le voir
# (Gael, 04/11/2026 : « le filtre ne fonctionne pas »).
COMPTES = [(key_of(objet, ("$.AccountId",)), objet) for objet in OBJETS]


async def _prepare(
    stack: EnvironnementStack, double: EnrolmentDouble, version: VersionFabriquee
) -> None:
    """Apparie, fait servir la version, puis écrit les comptes du jeu d'essai."""
    await sert(stack, double, version)
    for cle, objet in COMPTES:
        await stack.pool.execute(
            "INSERT INTO pudo.accounts (cle, objet, empreinte, version_modele)"
            " VALUES ($1, $2::jsonb, $3, 1)",
            cle,
            json.dumps(objet),
            b"\x00" * 32,
        )


async def _cherche(stack: EnvironnementStack, *, storage: str = "accounts", **params: Any) -> Any:
    reponse = await stack.client.get(f"/api/storages/{storage}/objects", params=params)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def test_la_cle_fonctionnelle_retrouve_un_objet(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        # La forme CANONIQUE, celle que l'ingestion écrit : un tableau JSON, même pour
        # une clé d'une seule partie. L'écrire en toutes lettres ici est volontaire — si
        # `key_of` change de forme, ce test doit rougir, pas suivre en silence.
        page = await _cherche(stack, f='cle:eq:["A-2"]')

        assert [o["cle"] for o in page["objects"]] == ['["A-2"]']
        assert page["total"] == 1
        assert page["objects"][0]["objet"]["Postes"] == 12
        # Les colonnes projetées voyagent avec l'objet : elles disent POURQUOI il est là.
        assert page["objects"][0]["columns"]["contact_phone"] == "0102999999"


async def test_la_cle_se_retrouve_par_une_de_ses_parties_sans_sa_forme_canonique(
    blank_db: str, tmp_path: Path
) -> None:
    """Ce que l'écran envoie par défaut : la personne tape « A-2 », pas `["A-2"]`.

    C'est l'opérateur « contient » qui traverse la forme canonique. Sans lui, filtrer sur
    la clé demandait de taper les crochets et les guillemets — autant dire ne pas filtrer.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="cle:contient:A-2")

        assert [o["cle"] for o in page["objects"]] == ['["A-2"]']


async def test_un_prefixe_sur_une_propriete_indexee_discrimine(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="contact_phone:prefixe:0102")

        assert sorted(o["cle"] for o in page["objects"]) == ['["A-1"]', '["A-2"]']


async def test_une_comparaison_numerique_rend_l_ordre_des_nombres_et_non_des_textes(
    blank_db: str, tmp_path: Path
) -> None:
    """LE critère qui prouve que la valeur n'est pas hachée — et qu'elle est bien typée.

    En `text`, « 12 » serait inférieur à « 3 » et ce test tomberait : c'est donc aussi la
    preuve que la colonne porte le type que le modèle garantit.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="postes:gt:5", tri="postes")

        assert [o["cle"] for o in page["objects"]] == ['["A-3"]', '["A-2"]']


async def test_des_criteres_combines_rendent_l_intersection(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f=["contact_phone:prefixe:0102", "postes:ge:10"])

        assert [o["cle"] for o in page["objects"]] == ['["A-2"]']


async def test_le_plan_d_execution_emprunte_l_index_declare(blank_db: str, tmp_path: Path) -> None:
    """Le gain qu'on achète avec le DDL doit être CONSTATÉ, pas supposé.

    Sur trois lignes PostgreSQL choisirait un parcours séquentiel, moins cher : on le lui
    interdit le temps de la mesure. Ce qu'on vérifie n'est pas qu'il préfère l'index,
    c'est qu'un index utilisable EXISTE et qu'il porte la colonne déclarée.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        async with stack.pool.acquire() as conn:
            await conn.execute("SET enable_seqscan = off")
            plan = await conn.fetchval(
                "EXPLAIN (FORMAT JSON) SELECT cle FROM pudo.accounts WHERE contact_phone = $1",
                "0102030405",
            )

        assert "accounts__tel" in json.dumps(plan)


async def test_un_critere_sur_une_propriete_non_declaree_est_refuse_et_nomme(
    blank_db: str, tmp_path: Path
) -> None:
    """Pas de repli silencieux sur un parcours de table : c'est une erreur d'appel."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        refus = await stack.client.get(
            "/api/storages/accounts/objects", params={"f": "contact_email:eq:x"}
        )

        assert refus.status_code == 422
        assert refus.json()["detail"] == {
            "code": "propriete_non_filtrable",
            "detail": "contact_email",
        }


async def test_la_pagination_ne_recouvre_rien_et_n_omet_rien(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        une = await _cherche(stack, page=1, taille=2)
        deux = await _cherche(stack, page=2, taille=2)

        assert len(une["objects"]) == 2
        assert len(deux["objects"]) == 1
        assert une["total"] == deux["total"] == 3
        vues = [o["cle"] for o in une["objects"]] + [o["cle"] for o in deux["objects"]]
        assert sorted(vues) == ['["A-1"]', '["A-2"]', '["A-3"]']


async def test_un_storage_vide_rend_une_page_vide_et_non_une_erreur(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await stack.client.get("/api/storages/sites/objects")

        assert page.status_code == 200, page.text
        assert page.json() == {"objects": [], "total": 0, "page": 1, "page_size": 50}


async def test_un_storage_inconnu_se_distingue_d_un_storage_vide(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        inconnu = await stack.client.get("/api/storages/fantome/objects")

        assert inconnu.status_code == 404
        assert inconnu.json()["detail"] == "storage_inconnu"


async def test_la_liste_des_storages_rend_la_declaration_et_l_etat_de_sa_table(
    blank_db: str, tmp_path: Path
) -> None:
    """Ce que le menu de gauche affiche : les espaces, et ce qu'on peut y filtrer."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        liste = await stack.client.get("/api/storages")

        assert liste.status_code == 200, liste.text
        comptes = next(item for item in liste.json() if item["name"] == "accounts")
        assert comptes["label"] == "Accounts"
        assert comptes["model"] == "pudo/accounts"
        assert comptes["schema_name"] == "pudo"
        assert comptes["keys"] == ["$.AccountId"]
        assert comptes["version_number"] == 1
        assert comptes["applied_at"] is not None
        assert comptes["refusal"] is None
        # Le chemin DÉCLARÉ voyage avec la colonne : l'écran montre ce que la personne a
        # choisi dans l'arbre des propriétés, pas le nom qu'on en a dérivé.
        assert comptes["projections"] == [
            {
                "column": "contact_phone",
                "path": "$.Contact.Phone",
                "kind": "string",
                "sql_type": "text",
            },
            # Le type vient du MODÈLE : c'est lui qui fera comparer des nombres et non
            # des textes, où « 12 » serait inférieur à « 3 ».
            {"column": "postes", "path": "$.Postes", "kind": "integer", "sql_type": "bigint"},
            # Une date reste `text`, et ce n'est pas un pis-aller : `format: date` est une
            # annotation, pas une garantie, et l'ordre lexicographique d'un ISO-8601 est
            # son ordre chronologique.
            {"column": "ouvert", "path": "$.Ouvert", "kind": "string", "sql_type": "text"},
        ]
        assert comptes["indexes"] == [
            {"name": "tel", "columns": ["contact_phone"]},
            {"name": "taille", "columns": ["postes"]},
            {"name": "ouverture", "columns": ["ouvert"]},
        ]


async def test_un_droit_de_lecture_est_exige(blank_db: str, tmp_path: Path) -> None:
    """Fail closed : la surface d'administration n'est pas ouverte à l'anonyme."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        for chemin in ("/api/storages", "/api/storages/schema", "/api/storages/accounts/objects"):
            refus = await stack.anonymous().get(chemin)
            assert refus.status_code == 401, (chemin, refus.status_code)


async def test_une_ecriture_applicative_d_une_colonne_projetee_est_REFUSEE_par_la_base(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, et c'est LA garantie que colonne et objet ne peuvent pas diverger.

    Ce n'est pas une discipline applicative qui l'assure : PostgreSQL REFUSE l'écriture.
    Du code qui prétendrait « maintenir » la colonne échouerait donc bruyamment, au lieu
    de poser une valeur qui contredirait le jsonb sans que rien ne le dise. C'est aussi ce
    qui rend un DDL sur ces colonnes incapable de détruire quoi que ce soit.

    Les DEUX gestes sont éprouvés : une insertion qui vise la colonne, et une mise à jour.
    N'en éprouver qu'un laisserait l'autre chemin ouvert.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        with pytest.raises(asyncpg.PostgresError) as insertion:
            await stack.pool.execute(
                "INSERT INTO pudo.accounts"
                " (cle, objet, empreinte, version_modele, contact_phone)"
                " VALUES ($1, $2::jsonb, $3, 1, $4)",
                "A-9",
                json.dumps({"AccountId": "A-9"}),
                b"\x00" * 32,
                "0000000000",
            )
        with pytest.raises(asyncpg.PostgresError) as mise_a_jour:
            await stack.pool.execute("UPDATE pudo.accounts SET contact_phone = $1", "0000000000")

        assert "contact_phone" in str(insertion.value)
        assert "contact_phone" in str(mise_a_jour.value)
        # Et rien n'a été écrit : le refus porte sur la ligne entière.
        assert await stack.pool.fetchval("SELECT count(*) FROM pudo.accounts") == len(COMPTES)


async def test_une_propriete_ABSENTE_de_l_objet_vaut_null_et_un_filtre_d_egalite_l_ecarte(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3, éprouvé sur `sites`, dont la v2 indexe le code postal.

    Deux objets, un seul porte la propriété : avec un jeu où tous la portent, un filtre
    qui confondrait « absent » et « vide » resterait vert. Et c'est bien la BASE qui rend
    `null`, puisque personne n'écrit la colonne.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[2])
        # Clés fabriquées comme en production, jamais à la main : c'est ce qui manquait
        # au jeu d'essai, et ce qui laissait passer une recherche par clé fausse.
        for objet in ({"Id": "S-1", "Zipcode": "59000"}, {"Id": "S-2"}):
            cle = key_of(objet, ("$.Id",))
            await stack.pool.execute(
                "INSERT INTO pudo.sites (cle, objet, empreinte, version_modele)"
                " VALUES ($1, $2::jsonb, $3, 2)",
                cle,
                json.dumps(objet),
                b"\x00" * 32,
            )

        manquante = await stack.pool.fetchval(
            "SELECT zipcode FROM pudo.sites WHERE cle = $1", '["S-2"]'
        )
        egalite = await _cherche(stack, storage="sites", f="zipcode:eq:59000")
        tous = await _cherche(stack, storage="sites")

        assert manquante is None
        assert [o["cle"] for o in egalite["objects"]] == ['["S-1"]']
        # L'objet sans la propriété reste dans le storage : il est écarté du FILTRE, pas
        # de la table, et la colonne nulle voyage avec lui.
        assert sorted(o["cle"] for o in tous["objects"]) == ['["S-1"]', '["S-2"]']
        sans = next(o for o in tous["objects"] if o["cle"] == '["S-2"]')
        assert sans["columns"]["zipcode"] is None


async def test_une_comparaison_sur_une_propriete_DATE_rend_l_ordre_chronologique(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5, second volet — le premier étant la comparaison numérique.

    La colonne est `text`, et c'est assumé : ce qui est éprouvé est que l'ordre
    lexicographique d'un ISO-8601 est bien l'ordre des dates, par-dessus un changement
    d'année, et qu'un intervalle se comporte comme on l'attend. Un hachage de la valeur
    ferait tomber les deux.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        apres_la_saint_sylvestre = await _cherche(stack, f="ouvert:gt:2025-12-31", tri="ouvert")
        intervalle = await _cherche(stack, f=["ouvert:ge:2026-01-10", "ouvert:le:2026-12-31"])
        chronologie = await _cherche(stack, tri="ouvert")

        # A-2 est ouvert le 31/12/2025 : exclu par la comparaison STRICTE.
        assert [o["cle"] for o in apres_la_saint_sylvestre["objects"]] == ['["A-1"]', '["A-3"]']
        assert [o["cle"] for o in intervalle["objects"]] == ['["A-3"]']
        # Le changement d'année est franchi dans le bon sens, et le 09 précède le 10.
        assert [o["cle"] for o in chronologie["objects"]] == ['["A-2"]', '["A-1"]', '["A-3"]']


async def test_le_TRI_sur_une_propriete_indexee_emprunte_son_index(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8 : un tri doit être SERVI par un index, pas seulement accepté.

    Le parcours séquentiel ET le tri explicite sont coupés le temps de la mesure : sur
    trois lignes PostgreSQL les choisirait, moins chers. Ce qui reste alors est le seul
    chemin qui produit l'ordre sans trier — la lecture ordonnée d'un index —, et c'est
    précisément ce qu'on veut constater.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        async with stack.pool.acquire() as conn:
            await conn.execute("SET enable_seqscan = off")
            await conn.execute("SET enable_sort = off")
            plan = await conn.fetchval(
                "EXPLAIN (FORMAT JSON) SELECT cle FROM pudo.accounts ORDER BY postes"
            )

        assert "accounts__taille" in json.dumps(plan)


async def test_aucun_objet_ne_satisfait_le_critere_rend_une_page_VIDE_et_non_une_erreur(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 15, distinct du storage vide (critère 14) : ici la table porte des objets,
    et c'est le filtre qui n'en retient aucun. Confondre les deux ferait rendre une erreur
    à un écran dont le filtre est simplement trop étroit."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="postes:gt:1000")

        assert page == {"objects": [], "total": 0, "page": 1, "page_size": 50}
        # La table n'est pas vide pour autant : c'est ce qui distingue ce cas du 14.
        assert (await _cherche(stack))["total"] == len(COMPTES)


async def test_une_table_en_retard_sur_la_version_servie_est_DITE(
    blank_db: str, tmp_path: Path
) -> None:
    """Et non une erreur SQL brute en 500 (incident du 05/11/2026).

    La déclaration suit la version servie ; la table, elle, ne change qu'à la POSE d'une
    version. Entre les deux l'écart est NORMAL, et le jour où le modèle s'est mis à
    déclarer des colonnes il est devenu courant : la lecture tombait sur
    « column "prop_id" does not exist », que personne ne peut relier à un geste.

    La colonne est retirée à la main ici, ce qui produit le même état que la version
    posée en retard — et couvre aussi la table retouchée hors de Miles.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])
        async with stack.pool.acquire() as conn:
            await conn.execute(f'ALTER TABLE "{WORKSPACE}".accounts DROP COLUMN contact_phone')

        reponse = await stack.client.get("/api/storages/accounts/objects")

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["detail"] == {"code": "table_en_retard", "detail": "contact_phone"}


async def test_un_storage_dont_la_table_n_existe_pas_est_dit_autrement(
    blank_db: str, tmp_path: Path
) -> None:
    # Deux refus distincts : « aucune version n'a jamais rien posé ici » ne se
    # diagnostique pas comme « une version plus récente n'est pas posée ».
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])
        async with stack.pool.acquire() as conn:
            await conn.execute(f'DROP TABLE "{WORKSPACE}".accounts')

        reponse = await stack.client.get("/api/storages/accounts/objects")

    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["detail"]["code"] == "table_absente"
