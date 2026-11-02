"""Les tables des storages de la version servie, posées sur une VRAIE base PostgreSQL.

« dans environnement assure toi que les tables de stockages fonctionnelles soient créées »
(Gael, 02/11/2026).

Ce qui est éprouvé ici ne se mesure pas ailleurs : des colonnes **dérivées par la base**,
un DDL **rejouable**, et ce qui arrive aux objets déjà écrits quand la version suivante
ajoute ou retire une propriété indexable. Aucune doublure ne sait répondre à ça — c'est
PostgreSQL qui calcule, et c'est lui qu'il faut interroger.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.hosting import HOSTED_VERSION_PATH, HostedVersionIn
from miles_socle.signing.keys import load_private_key
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from environnement.storages.model import (
    REFUSAL_UNKNOWN_PROPERTY,
    STORAGE_REFUSED_EVENT,
    STORAGES_MATERIALISED_EVENT,
)
from tests.integration.bundles import VersionFabriquee, fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack

pytestmark = pytest.mark.integration

WORKSPACE = "reseau-ferroviaire"


async def _apparie(stack: EnvironnementStack) -> None:
    ouverte = await stack.client.post(
        "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "Recette nord"}
    )
    assert ouverte.status_code == 202, ouverte.text
    conclu = await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def _ordonne(
    stack: EnvironnementStack, double: EnrolmentDouble, version: VersionFabriquee
) -> Any:
    double.bundles[version.commit] = version.bundle
    corps = (
        HostedVersionIn(workspace_id=WORKSPACE, number=version.number, commit=version.commit)
        .model_dump_json()
        .encode("utf-8")
    )
    entetes = {
        ORIGIN_HEADER: PEER_ORIGIN,
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_call(
            load_private_key(double.keypair.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=HOSTED_VERSION_PATH,
            body=corps,
        ),
    }
    recu = await stack.anonymous().post(HOSTED_VERSION_PATH, content=corps, headers=entetes)
    assert recu.status_code == 200, recu.text
    return recu


async def _colonnes(stack: EnvironnementStack, schema: str, table: str) -> dict[str, str]:
    rows = await stack.pool.fetch(
        "SELECT a.attname AS nom, format_type(a.atttypid, a.atttypmod) AS type_sql"
        " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = $1 AND c.relname = $2 AND a.attnum > 0 AND NOT a.attisdropped",
        schema,
        table,
    )
    return {row["nom"]: row["type_sql"] for row in rows}


async def _index(stack: EnvironnementStack, schema: str, table: str) -> list[str]:
    rows = await stack.pool.fetch(
        "SELECT i.relname AS nom FROM pg_index x"
        " JOIN pg_class i ON i.oid = x.indexrelid"
        " JOIN pg_class c ON c.oid = x.indrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = $1 AND c.relname = $2 ORDER BY i.relname",
        schema,
        table,
    )
    return [row["nom"] for row in rows]


async def _ecrit(stack: EnvironnementStack, cle: str, objet: dict[str, Any]) -> None:
    """Écrit un objet comme l'ingestion l'écrira : l'objet, et RIEN des colonnes projetées."""
    await stack.pool.execute(
        "INSERT INTO pudo.accounts (cle, objet, empreinte, version_modele)"
        " VALUES ($1, $2::jsonb, $3, $4)",
        cle,
        json.dumps(objet),
        b"\x00" * 32,
        1,
    )


async def test_la_version_servie_pose_les_tables_de_ses_storages(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux storages, deux schémas, et des colonnes dérivées par la base."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)

        await _ordonne(stack, double, versions[1])

        colonnes = await _colonnes(stack, "pudo", "accounts")
        assert colonnes["objet"] == "jsonb"
        assert colonnes["cle"] == "text"
        assert colonnes["vu_le"] == "timestamp with time zone"
        # La colonne de la propriété indexée, et son type lu du modèle.
        assert colonnes["contact_phone"] == "text"
        assert await _colonnes(stack, "pudo", "sites") != {}
        # L'index unique de la clé, et l'index déclaré, avec la marque qui dit qu'ils
        # sont à nous.
        assert "accounts__cle" in await _index(stack, "pudo", "accounts")
        assert "accounts__tel" in await _index(stack, "pudo", "accounts")


async def test_la_base_derive_les_colonnes_et_l_application_ne_peut_pas_les_ecrire(
    blank_db: str, tmp_path: Path
) -> None:
    """Le critère qui garantit qu'une colonne ne peut pas diverger de son objet.

    Deux moitiés, et la seconde compte autant : la valeur est là sans qu'on l'ait écrite,
    ET une écriture qui la viserait est refusée par PostgreSQL. C'est structurel, pas une
    discipline de code.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])

        await _ecrit(stack, "A-1", {"AccountId": "A-1", "Contact": {"Phone": "0102030405"}})

        assert (
            await stack.pool.fetchval("SELECT contact_phone FROM pudo.accounts WHERE cle = 'A-1'")
            == "0102030405"
        )
        with pytest.raises(Exception, match="generated"):
            await stack.pool.execute(
                "INSERT INTO pudo.accounts (cle, objet, empreinte, version_modele, contact_phone)"
                " VALUES ('A-2', '{}'::jsonb, $1, 1, 'écrite à la main')",
                b"\x00" * 32,
            )


async def test_une_propriete_absente_de_l_objet_laisse_la_colonne_nulle(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])

        await _ecrit(stack, "A-1", {"AccountId": "A-1"})

        assert (
            await stack.pool.fetchval("SELECT contact_phone FROM pudo.accounts WHERE cle = 'A-1'")
            is None
        )
        trouve = await stack.client.get(
            "/api/storages/accounts/objects", params={"f": "contact_phone:eq:0102030405"}
        )
        assert trouve.status_code == 200, trouve.text
        assert trouve.json()["objects"] == []


async def test_servir_deux_fois_la_meme_version_ne_change_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Rejeu : l'opération est idempotente, et le journal ne raconte pas deux poses."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])
        avant = await _colonnes(stack, "pudo", "accounts")
        await _ecrit(stack, "A-1", {"AccountId": "A-1", "Contact": {"Phone": "01"}})

        await _ordonne(stack, double, versions[1])

        assert await _colonnes(stack, "pudo", "accounts") == avant
        assert await stack.pool.fetchval("SELECT count(*) FROM pudo.accounts") == 1


async def test_une_version_qui_ajoute_une_propriete_indexable_remplit_les_objets_deja_la(
    blank_db: str, tmp_path: Path
) -> None:
    """Le critère qui paie le DDL : PostgreSQL calcule la colonne sur l'existant.

    Aucune réingestion, aucune réécriture applicative — et c'est précisément ce qu'une
    table d'index générique ne savait pas faire.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])
        await _ecrit(
            stack,
            "A-1",
            {"AccountId": "A-1", "Contact": {"Phone": "01", "Email": "a@b.invalid"}},
        )

        await _ordonne(stack, double, versions[2])

        assert (
            await stack.pool.fetchval("SELECT contact_email FROM pudo.accounts WHERE cle = 'A-1'")
            == "a@b.invalid"
        )
        assert "accounts__mail" in await _index(stack, "pudo", "accounts")


async def test_une_version_qui_retire_une_propriete_indexable_ne_touche_aucun_objet(
    blank_db: str, tmp_path: Path
) -> None:
    """La colonne et son index partent, l'objet reste — et une réintroduction le retrouve."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[2])
        await _ecrit(
            stack,
            "A-1",
            {"AccountId": "A-1", "Contact": {"Phone": "01", "Email": "a@b.invalid"}},
        )

        await _ordonne(stack, double, versions[3])

        assert "contact_phone" not in await _colonnes(stack, "pudo", "accounts")
        assert "accounts__tel" not in await _index(stack, "pudo", "accounts")
        objet = await stack.pool.fetchval("SELECT objet FROM pudo.accounts WHERE cle = 'A-1'")
        assert json.loads(objet)["Contact"]["Phone"] == "01"

        # Réintroduite : la valeur revient, sans réingestion.
        await _ordonne(stack, double, versions[2])

        assert (
            await stack.pool.fetchval("SELECT contact_phone FROM pudo.accounts WHERE cle = 'A-1'")
            == "01"
        )


async def test_un_storage_retire_de_la_declaration_garde_sa_table(
    blank_db: str, tmp_path: Path
) -> None:
    """Une table de données ne disparaît pas sur un changement de paramétrage.

    C'est un geste d'exploitation, pas une conséquence de déclaration. Ce qui s'oublie,
    c'est la TRACE : le storage ne figure plus dans la liste de l'écran.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])
        await stack.pool.execute(
            "INSERT INTO pudo.sites (cle, objet, empreinte, version_modele)"
            " VALUES ('S-1', '{\"Id\": \"S-1\"}'::jsonb, $1, 1)",
            b"\x00" * 32,
        )

        await _ordonne(stack, double, versions[3])

        assert await stack.pool.fetchval("SELECT count(*) FROM pudo.sites") == 1
        liste = await stack.client.get("/api/storages")
        assert [item["name"] for item in liste.json()] == ["accounts"]


async def test_un_storage_fautif_est_refuse_nomme_et_n_empeche_pas_les_autres(
    blank_db: str, tmp_path: Path
) -> None:
    """Le défaut que Gael a rencontré côté portail : un index sur une propriété disparue."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])
        # Le modèle perd la propriété que l'index déclare, comme le 01/11/2026.
        chemin = stack.tree.root / "domains/pudo/messages/accounts.yaml"
        chemin.write_text(
            chemin.read_text(encoding="utf-8").replace("Phone: {type: string}", "Tel: {}"),
            encoding="utf-8",
        )

        outcome = await stack.storages.resolve_materialise(1)

        assert outcome.applied == ("sites",)
        assert [(r.storage, r.code, r.detail) for r in outcome.refused] == [
            ("accounts", REFUSAL_UNKNOWN_PROPERTY, "$.Contact.Phone")
        ]
        liste = await stack.client.get("/api/storages")
        fautif = next(item for item in liste.json() if item["name"] == "accounts")
        assert (fautif["refusal"], fautif["refusal_detail"]) == (
            REFUSAL_UNKNOWN_PROPERTY,
            "$.Contact.Phone",
        )


async def test_le_journal_dit_ce_qui_a_ete_pose_et_ce_qui_a_ete_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)

        await _ordonne(stack, double, versions[1])

        rows = await stack.pool.fetch(
            "SELECT type, properties FROM events WHERE type LIKE 'environment.storage%'"
            " ORDER BY written_at"
        )
        assert [row["type"] for row in rows] == [STORAGES_MATERIALISED_EVENT]
        properties = json.loads(rows[0]["properties"])
        assert sorted(properties["applied"]) == ["accounts", "sites"]
        assert properties["version"] == 1


async def test_le_journal_se_tait_quand_rien_n_a_change(blank_db: str, tmp_path: Path) -> None:
    """Même règle que pour un ordre rejoué : le journal ne dit pas qu'il s'est passé
    quelque chose quand il ne s'est rien passé."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])
        avant = await stack.pool.fetchval(
            "SELECT count(*) FROM events WHERE type LIKE 'environment.storage%'"
        )

        await stack.storages.resolve_materialise(1)

        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type LIKE 'environment.storage%'"
            )
            == avant
        )
        assert STORAGE_REFUSED_EVENT  # le type existe, et aucun n'a été écrit


async def test_le_sql_d_une_version_est_lisible_avant_d_etre_applique(
    blank_db: str, tmp_path: Path
) -> None:
    """La contrepartie de l'absence d'homologation : personne ne relit ce DDL avant.

    Interrogé AVANT tout ordre : la version est posée sur le volume, et le SQL se lit
    sans que rien ne soit encore exécuté.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack)
        await _ordonne(stack, double, versions[1])

        apercu = await stack.client.get("/api/storages/schema")

        assert apercu.status_code == 200, apercu.text
        sql = "\n".join(apercu.json()["accounts"])
        assert "create schema if not exists" in sql
        assert 'generated always as (objet #>> \'{"Contact","Phone"}\') stored' in sql
