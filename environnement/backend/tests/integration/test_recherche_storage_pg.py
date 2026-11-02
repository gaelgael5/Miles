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

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from tests.integration.bundles import VersionFabriquee, fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

WORKSPACE = "reseau-ferroviaire"
# Trois comptes, dont deux partagent un préfixe de téléphone : un jeu où chaque filtre
# doit DISCRIMINER. Avec des valeurs toutes différentes, un filtre faux resterait vert.
COMPTES = [
    ("A-1", {"AccountId": "A-1", "Postes": 3, "Contact": {"Phone": "0102030405"}}),
    ("A-2", {"AccountId": "A-2", "Postes": 12, "Contact": {"Phone": "0102999999"}}),
    ("A-3", {"AccountId": "A-3", "Postes": 7, "Contact": {"Phone": "0600000000"}}),
]


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


async def _cherche(stack: EnvironnementStack, **params: Any) -> Any:
    reponse = await stack.client.get("/api/storages/accounts/objects", params=params)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


async def test_la_cle_fonctionnelle_retrouve_un_objet(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="cle:eq:A-2")

        assert [o["cle"] for o in page["objects"]] == ["A-2"]
        assert page["total"] == 1
        assert page["objects"][0]["objet"]["Postes"] == 12
        # Les colonnes projetées voyagent avec l'objet : elles disent POURQUOI il est là.
        assert page["objects"][0]["columns"]["contact_phone"] == "0102999999"


async def test_un_prefixe_sur_une_propriete_indexee_discrimine(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f="contact_phone:prefixe:0102")

        assert sorted(o["cle"] for o in page["objects"]) == ["A-1", "A-2"]


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

        assert [o["cle"] for o in page["objects"]] == ["A-3", "A-2"]


async def test_des_criteres_combines_rendent_l_intersection(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _prepare(stack, double, versions[1])

        page = await _cherche(stack, f=["contact_phone:prefixe:0102", "postes:ge:10"])

        assert [o["cle"] for o in page["objects"]] == ["A-2"]


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
        assert sorted(vues) == ["A-1", "A-2", "A-3"]


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
        ]
        assert comptes["indexes"] == [
            {"name": "tel", "columns": ["contact_phone"]},
            {"name": "taille", "columns": ["postes"]},
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
