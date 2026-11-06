"""La file, les bornes du disque et l'entretien des imports (story 0f14adbd).

Ce que seule une VRAIE base peut dire, et qu'aucune doublure ne prouve :

- qu'un **verrou consultatif** sérialise réellement deux imports d'un même storage
  (critère 12) — un verrou de processus n'en aurait rien su ;
- qu'un import laissé **en cours** par un arrêt est rattrapé, ou tombe en échec si son
  document n'est plus là (critère 14) ;
- que la **purge** ôte le document sans jamais ôter l'historique (critère 16), qu'elle part
  du plus ancien, et qu'elle épargne un document dont l'import est en file (critère 17) ;
- qu'un dépôt est refusé **avant** d'être lu quand le disque ne peut pas l'accueillir
  (critères 18 et 19).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest_file import INGEST_FILE_PATH
from environnement.ingestion.api_maintenance import IMPORTS_MAINTENANCE_PATH
from environnement.ingestion.applystaging import FAILURE_APPLY_TOO_LONG
from environnement.ingestion.fileimport import FAILURE_FILE_MISSING, LOCK_PREFIX
from environnement.ingestion.files import REFUSAL_FILE_TOO_LARGE, REFUSAL_QUOTA_REACHED
from environnement.ingestion.outcome import (
    STATE_FAILED_IMPORT,
    STATE_PROCESSED,
    STATE_QUEUED,
    STATE_RUNNING,
)
from tests.integration.bundles import fabrique_import_fichier
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
STORAGE = "magasins"
JETON = "jeton-d-entretien"


def _item(code: str) -> dict[str, Any]:
    return {"code": code, "nom": f"Magasin {code}", "ville": "Paris", "postes": 3}


def _document(codes: list[str]) -> bytes:
    return json.dumps({"magasins": [_item(code) for code in codes]}).encode()


@asynccontextmanager
async def _ouvre(
    blank_db: str, tmp_path: Path, **bornes: Any
) -> AsyncIterator[tuple[EnvironnementStack, str]]:
    """Une stack qui sert la source en mode fichier, avec sa clé d'API et son jeton."""
    versions = fabrique_import_fichier(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app(), **bornes) as stack:
        await sert(stack, double, versions[1])
        # Le jeton d'entretien est posé par la durée de vie en production ; ici le test
        # le pose, parce que c'est lui qui joue le déclencheur d'hôte.
        stack.app.state.journal_maintenance_token = JETON
        recu = await stack.client.post(
            "/api/api-keys", json={"label": "Transporteur", "sources": [SOURCE]}
        )
        assert recu.status_code == 201, recu.text
        yield stack, recu.json()["secret"]


async def _depose(stack: EnvironnementStack, secret: str, codes: list[str], **entetes: str) -> Any:
    return await stack.anonymous().post(
        INGEST_FILE_PATH.format(source=SOURCE),
        content=_document(codes),
        headers={"X-API-Key": secret, "Content-Type": "application/json", **entetes},
    )


async def _etat(stack: EnvironnementStack, ingestion_id: str) -> Any:
    return await stack.pool.fetchrow(
        "SELECT state, items_read, failure_code, failure_detail, file_name, file_purged_at"
        " FROM ingestions WHERE id = $1",
        ingestion_id,
    )


async def _entretien(stack: EnvironnementStack, *, jeton: str = JETON) -> Any:
    return await stack.client.post(
        IMPORTS_MAINTENANCE_PATH, headers={"Authorization": f"Bearer {jeton}"}
    )


async def _cles(stack: EnvironnementStack) -> set[str]:
    rows = await stack.pool.fetch(f"SELECT cle FROM pudo.{STORAGE}")  # noqa: S608
    return {row["cle"] for row in rows}


async def test_un_import_n_est_pas_mene_pendant_qu_un_autre_tient_le_storage(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12 : jamais deux imports en parallèle sur le même storage.

    Le verrou est pris sur une AUTRE connexion, comme le ferait une autre instance de la
    stack : c'est ce que le critère demande, et un verrou de processus n'aurait rien vu.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, secret):
        recu = await _depose(stack, secret, ["M-1"])
        async with stack.pool.acquire() as autre:
            pris = await autre.fetchval(
                "SELECT pg_try_advisory_lock(hashtext($1))", f"{LOCK_PREFIX}{STORAGE}"
            )
            assert pris is True

            await stack.resolve_imports()

            # L'import n'est pas perdu : il attend son tour, et rien n'est écrit.
            assert (await _etat(stack, recu.json()["id"]))["state"] == STATE_QUEUED
            assert await _cles(stack) == set()
            await autre.execute(
                "SELECT pg_advisory_unlock(hashtext($1))", f"{LOCK_PREFIX}{STORAGE}"
            )

        # Le verrou rendu, l'entretien rattrape la file : c'est son rôle.
        rendu = await _entretien(stack)

        assert rendu.status_code == 200, rendu.text
        assert rendu.json()["drained"] == 1
        assert await _cles(stack) == {'["M-1"]'}


async def test_un_import_laisse_en_cours_par_un_arret_est_remis_en_file(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 14 : jamais laissé dans un état indéterminé, et rejouable depuis le
    document.

    Rejouer est sûr parce que l'écriture est DIFFÉRENTIELLE : un item déjà écrit par la
    tentative interrompue ressort « inchangé ».
    """
    async with _ouvre(blank_db, tmp_path) as (stack, secret):
        recu = await _depose(stack, secret, ["M-1"])
        ingestion = recu.json()["id"]
        # Ce qu'un conteneur arrêté au milieu d'un import laisse derrière lui : l'état
        # « en cours », et personne pour le mener.
        await stack.pool.execute(
            "UPDATE ingestions SET state = $2 WHERE id = $1", ingestion, STATE_RUNNING
        )
        stack.lancements.clear()

        rendu = await _entretien(stack)

        assert rendu.json()["requeued"] == 1
        # Et la file est drainée dans le même passage : l'import aboutit.
        assert (await _etat(stack, ingestion))["state"] == STATE_PROCESSED
        assert await _cles(stack) == {'["M-1"]'}


async def test_un_import_en_cours_dont_le_document_a_disparu_tombe_en_echec(
    blank_db: str, tmp_path: Path
) -> None:
    """L'autre moitié du critère 14 : ou rejouable, ou en échec — jamais indéterminé."""
    async with _ouvre(blank_db, tmp_path) as (stack, secret):
        recu = await _depose(stack, secret, ["M-1"])
        ingestion = recu.json()["id"]
        await stack.pool.execute(
            "UPDATE ingestions SET state = $2 WHERE id = $1", ingestion, STATE_RUNNING
        )
        stack.lancements.clear()
        await stack.ingestion_files.file_remove(ingestion)

        rendu = await _entretien(stack)

        assert rendu.json()["failed"] == 1
        etat = await _etat(stack, ingestion)
        assert (etat["state"], etat["failure_code"]) == (STATE_FAILED_IMPORT, FAILURE_FILE_MISSING)


async def test_un_fichier_sans_ligne_est_ote_par_l_entretien(blank_db: str, tmp_path: Path) -> None:
    """Le fichier temporaire ne fuit pas (critère 14), pas même celui d'un dépôt
    interrompu avant son inscription."""
    async with _ouvre(blank_db, tmp_path) as (stack, _):
        orphelin = "f" * 32
        store = stack.ingestion_files
        store.root.mkdir(parents=True, exist_ok=True)
        store.file_path(orphelin).write_bytes(b"{}")

        rendu = await _entretien(stack)

        assert rendu.json()["orphan_files_removed"] == 1
        assert await store.file_names() == set()


async def test_un_document_expire_est_purge_et_son_historique_reste(
    blank_db: str, tmp_path: Path
) -> None:
    """Critères 15 et 16 : le document est conservé, puis purgé — l'historique jamais."""
    async with _ouvre(blank_db, tmp_path, retention_days=7) as (stack, secret):
        recu = await _depose(stack, secret, ["M-1"])
        ingestion = recu.json()["id"]
        await stack.resolve_imports()
        assert await stack.ingestion_files.file_names() == {ingestion}

        # Le dépôt vieillit de huit jours : c'est la seule variable qu'on déplace.
        await stack.pool.execute(
            "UPDATE ingestions SET received_at = received_at - $2::interval WHERE id = $1",
            ingestion,
            timedelta(days=8),
        )
        rendu = await _entretien(stack)

        assert rendu.json()["purged_expired"] == 1
        assert await stack.ingestion_files.file_names() == set()
        etat = await _etat(stack, ingestion)
        assert etat["state"] == STATE_PROCESSED
        assert etat["file_purged_at"] is not None
        assert etat["file_name"] == ingestion


async def test_la_purge_de_quota_part_du_plus_ancien_et_epargne_un_import_en_file(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 17 : par ancienneté d'abord, et JAMAIS un document encore à importer.

    Purger celui-là ferait échouer un import légitime — c'est précisément ce que la
    pression de quota pousse à faire, et ce qu'il ne faut pas faire.

    **Le quota est MESURÉ, pas supposé** : les deux documents sont déposés sous le quota
    de production, puis l'entretien est monté avec un quota tenu par un seul d'entre eux.
    Deviner leur taille pour choisir un chiffre aurait fait un test qui passe ou tombe
    selon la longueur d'un libellé.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, secret):
        vieux = (await _depose(stack, secret, ["M-1"])).json()["id"]
        await stack.resolve_imports()
        recent = (await _depose(stack, secret, ["M-2"])).json()["id"]
        # `recent` n'est PAS importé : son import est encore en file.
        assert (await _etat(stack, recent))["state"] == STATE_QUEUED
        await stack.pool.execute(
            "UPDATE ingestions SET received_at = received_at - $2::interval WHERE id = $1",
            vieux,
            timedelta(hours=1),
        )
        occupe = await stack.ingestion_files.file_used_bytes()
        serre = replace(stack.ingestion_files, quota_bytes=occupe - 1)
        entretien = replace(stack.ingestion_maintenance, files=serre)

        rapport = await entretien.resolve_maintain()

        assert rapport.purged_for_quota == 1
        assert (await _etat(stack, vieux))["file_purged_at"] is not None
        # Le plus récent reste : son import est en file, et le purger le ferait échouer.
        assert (await _etat(stack, recent))["file_purged_at"] is None


async def test_un_depot_qui_depasse_le_quota_est_refuse_avant_d_etre_lu(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 18 : refusé en nommant le quota, et rien n'est posé sur le disque."""
    async with _ouvre(blank_db, tmp_path, files_quota_bytes=120) as (stack, secret):
        premier = await _depose(stack, secret, ["M-1"])
        assert premier.status_code == 202, premier.text

        refuse = await _depose(stack, secret, ["M-2"])

        assert refuse.status_code == 413
        assert refuse.json()["detail"] == {"code": REFUSAL_QUOTA_REACHED, "detail": "120"}
        assert await stack.ingestion_files.file_names() == {premier.json()["id"]}


async def test_un_depot_plus_gros_que_la_borne_est_refuse_avec_la_borne(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 19 : la borne est dans le message, sinon on ne sait pas comment découper."""
    async with _ouvre(blank_db, tmp_path, file_max_bytes=50) as (stack, secret):
        refuse = await _depose(stack, secret, ["M-1", "M-2", "M-3"])

        assert refuse.status_code == 413
        assert refuse.json()["detail"] == {"code": REFUSAL_FILE_TOO_LARGE, "detail": "50"}
        assert await stack.ingestion_files.file_names() == set()


async def test_un_plafond_de_duree_depasse_termine_l_import_en_echec(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13 : l'écriture ne reste pas ouverte, elle échoue — et rien n'est écrit.

    Le plafond est posé à zéro, ce qui est la seule façon DÉTERMINISTE de le franchir :
    une borne courte mais non nulle dépend de la vitesse de la machine, et un test qui
    dépend de l'horloge échoue un jour sur cent.
    """
    async with _ouvre(blank_db, tmp_path, apply_seconds=0.000_001) as (stack, secret):
        recu = await _depose(stack, secret, ["M-1", "M-2"])
        await stack.resolve_imports()

        etat = await _etat(stack, recu.json()["id"])
        assert (etat["state"], etat["failure_code"]) == (
            STATE_FAILED_IMPORT,
            FAILURE_APPLY_TOO_LONG,
        )
        assert await _cles(stack) == set()


async def test_la_route_d_entretien_refuse_sans_le_secret_de_stack(
    blank_db: str, tmp_path: Path
) -> None:
    """Fail closed : une route d'entretien ouverte laisse n'importe qui PURGER."""
    async with _ouvre(blank_db, tmp_path) as (stack, _):
        sans = await stack.client.post(IMPORTS_MAINTENANCE_PATH)
        faux = await _entretien(stack, jeton="pas-le-bon")

        assert sans.status_code == 401
        assert faux.status_code == 401


async def test_en_regime_etabli_la_transaction_d_ecriture_est_courte(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9, second temps : MESURÉ, et sur le régime que le ticket décrit.

    Le régime établi est celui d'un réimport : l'écriture différentielle ne touche aucun
    corps, et la transaction ne fait que confronter des empreintes, là où la préparation
    évalue le template item par item. C'est la comparaison que le ticket demande, et elle
    porte sur un RAPPORT — comparer des durées absolues mesurerait la machine.

    **Six cents items et non soixante, depuis le 06/11/2026.** À soixante, les deux côtés
    du rapport étaient dominés par des coûts FIXES et non par le travail : mesuré sur
    `host-test-37`, planifier l'instruction de fusion coûte 1,9 ms et l'exécuter sur
    soixante items 6,2 ms, quand la transaction entière en prenait 118 — le reste étant
    les sept allers-retours de l'écriture vers une base d'un autre conteneur. Le jour où
    la préparation est passée du `executemany` au `COPY`, le total a diminué sans que ces
    allers-retours bougent, et le rapport a franchi la moitié : le test rougissait d'une
    optimisation. Ce que le critère dit est que la part qui CROÎT avec le document — le
    template, item par item — est hors de la transaction ; il faut donc assez d'items pour
    que cette part domine les constantes des deux côtés.
    """
    codes = [f"M-{n}" for n in range(1, 601)]
    async with _ouvre(blank_db, tmp_path) as (stack, secret):
        await _depose(stack, secret, codes)
        await stack.resolve_imports()

        recu = await _depose(stack, secret, codes)
        await stack.resolve_imports()

        ligne = await stack.pool.fetchrow(
            "SELECT started_at, apply_started_at, finished_at FROM ingestions WHERE id = $1",
            recu.json()["id"],
        )
        total = (ligne["finished_at"] - ligne["started_at"]).total_seconds()
        ecriture = (ligne["finished_at"] - ligne["apply_started_at"]).total_seconds()
        assert total > 0
        assert ecriture < total / 2
