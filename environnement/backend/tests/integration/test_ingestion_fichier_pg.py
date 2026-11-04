"""Le mode GROS FICHIER sur une VRAIE base PostgreSQL (story 0f14adbd).

**C'est ici que l'asynchronie se prouve.** Le dépôt rend un acquittement de prise en charge
et ne lit rien ; l'import se déroule après, et c'est l'historique des ingestions qui porte
son issue. Un test qui déposerait et vérifierait la table dans le même souffle mesurerait
une promesse que le service ne fait pas.

**Les imports sont déroulés EXPLICITEMENT** (`stack.resolve_imports()`). En production c'est
une tâche détachée ; ici le harnais les garde, pour que le test décide quand l'import tourne
— et c'est ce qui permet d'affirmer que le dépôt a rendu son accusé AVANT que le document
soit lu. Un test qui n'attend pas une tâche de fond ne prouve rien (leçon du 24/10/2026).

L'entretien, la file, la rétention et le quota sont dans `test_ingestion_fichier_entretien_pg`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest import IDEMPOTENCY_HEADER
from environnement.ingestion.api_ingest_file import INGEST_FILE_PATH
from environnement.ingestion.jsonflux import ITEMS_PATH_ABSENT, ITEMS_PATH_NOT_ARRAY
from environnement.ingestion.model import OCTET_STREAM
from environnement.ingestion.outcome import (
    ANOMALY_DUPLICATE_KEY,
    STATE_FAILED_IMPORT,
    STATE_PARTIAL,
    STATE_PROCESSED,
    STATE_QUEUED,
)
from tests.integration.bundles import fabrique_import_fichier
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
SCHEMA, TABLE = "pudo", "magasins"
M1, M2, M3 = '["M-1"]', '["M-2"]', '["M-3"]'


def _item(code: str, ville: str = "Paris", postes: int = 3) -> dict[str, Any]:
    return {"code": code, "nom": f"Magasin {code}", "ville": ville, "postes": postes}


def _document(items: list[dict[str, Any]], **entete: Any) -> bytes:
    """Un document dont les items sont AU MILIEU : des clés avant et après le tableau.

    Après autant qu'avant, et c'est voulu : un en-tête placé après le tableau arriverait
    trop tard pour une lecture qui ne revient pas en arrière, et c'est ce que la double
    passe existe pour lever (critère 6).
    """
    corps = {"genere_le": "2026-11-04", "magasins": items, **entete}
    return json.dumps(corps).encode()


@dataclass
class _Depot:
    stack: EnvironnementStack
    secret: str

    async def depose(
        self,
        corps: bytes,
        *,
        idempotence: str | None = None,
        content_type: str = "application/json",
    ) -> Any:
        entetes = {"X-API-Key": self.secret, "Content-Type": content_type}
        if idempotence is not None:
            entetes[IDEMPOTENCY_HEADER] = idempotence
        return await self.stack.anonymous().post(
            INGEST_FILE_PATH.format(source=SOURCE), content=corps, headers=entetes
        )

    async def ingestion(self, ingestion_id: str) -> Any:
        return await self.stack.pool.fetchrow(
            "SELECT state, items_read, object_count, metadata::text AS metadata,"
            " report::text AS report, failure_code, failure_detail, file_name,"
            " file_purged_at, started_at, apply_started_at, finished_at"
            " FROM ingestions WHERE id = $1",
            ingestion_id,
        )

    async def lignes(self) -> dict[str, Any]:
        rows = await self.stack.pool.fetch(
            f"SELECT cle, objet::text AS objet, vu_le, modifie_le, ville"  # noqa: S608
            f" FROM {SCHEMA}.{TABLE}"
        )
        return {row["cle"]: row for row in rows}

    async def staging(self) -> int:
        row = await self.stack.pool.fetchrow("SELECT count(*) AS n FROM ingestion_staging")
        return int(row["n"])


@asynccontextmanager
async def _ouvre(
    blank_db: str, tmp_path: Path, **declaration: Any
) -> AsyncIterator[tuple[EnvironnementStack, _Depot]]:
    """Une stack qui SERT une source en mode fichier, avec sa clé d'API."""
    apply_seconds = declaration.pop("apply_seconds", None)
    retention_days = declaration.pop("retention_days", None)
    versions = fabrique_import_fichier(tmp_path, **declaration)
    double = EnrolmentDouble()
    async with open_stack(
        blank_db,
        tmp_path,
        peer_app=double.app(),
        apply_seconds=apply_seconds,
        retention_days=retention_days,
    ) as stack:
        await sert(stack, double, versions[1])
        recu = await stack.client.post(
            "/api/api-keys", json={"label": "Transporteur", "sources": [SOURCE]}
        )
        assert recu.status_code == 201, recu.text
        yield stack, _Depot(stack, recu.json()["secret"])


async def test_un_depot_de_fichier_est_pris_en_charge_sans_rien_lire(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1, premier temps : l'accusé ne promet QUE la prise en charge."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        recu = await depot.depose(_document([_item("M-1"), _item("M-2")]))

        assert recu.status_code == 202, recu.text
        accuse = recu.json()
        assert accuse["state"] == STATE_QUEUED
        assert accuse["report"] is None
        assert accuse["object_count"] == 0
        # Rien n'est lu, donc rien n'est écrit : la table du storage est vide, et le
        # document attend sur le disque.
        assert await depot.lignes() == {}
        ligne = await depot.ingestion(accuse["id"])
        assert ligne["file_name"] == accuse["id"]


async def test_l_import_ecrit_les_items_du_decoupage_et_range_les_metadonnees(
    blank_db: str, tmp_path: Path
) -> None:
    """Critères 1 et 6 : un item par ligne, et l'en-tête du document lu par la double
    passe."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        recu = await depot.depose(_document([_item("M-1"), _item("M-2")], total=2))
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["state"] == STATE_PROCESSED
        assert (ligne["items_read"], ligne["object_count"]) == (2, 2)
        # `total` est placé APRÈS le tableau dans le document : il n'est lisible que
        # parce qu'une première passe le cherche sans construire les items.
        assert json.loads(ligne["metadata"]) == {"genere_le": "2026-11-04", "total": 2}
        rapport = json.loads(ligne["report"])
        assert (rapport["received"], rapport["written"]) == (2, 2)
        assert (rapport["unchanged"], rapport["rejected"]) == (0, 0)
        lignes = await depot.lignes()
        assert set(lignes) == {M1, M2}
        assert json.loads(lignes[M1]["objet"]) == {
            "Code": "M-1",
            "Libelle": "Magasin M-1",
            "Ville": "Paris",
            "Postes": 3,
        }
        # Colonne DÉRIVÉE par la base, sans qu'aucune écriture de l'import ne la vise
        # (critère 11).
        assert lignes[M1]["ville"] == "Paris"
        # L'aire de préparation est un brouillon : elle ne survit pas à l'import.
        assert await depot.staging() == 0


async def test_un_reimport_a_l_identique_n_ecrit_aucun_corps(blank_db: str, tmp_path: Path) -> None:
    """Critère 10 : `vu_le` avance sur tous les items vus, `modifie_le` ne bouge pas."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        items = [_item("M-1"), _item("M-2")]
        await depot.depose(_document(items))
        await stack.resolve_imports()
        avant = await depot.lignes()

        recu = await depot.depose(_document(items))
        await stack.resolve_imports()

        rapport = json.loads((await depot.ingestion(recu.json()["id"]))["report"])
        assert (rapport["written"], rapport["unchanged"]) == (0, 2)
        apres = await depot.lignes()
        assert apres[M1]["vu_le"] > avant[M1]["vu_le"]
        assert apres[M1]["modifie_le"] == avant[M1]["modifie_le"]


async def test_un_tableau_vide_est_une_ingestion_de_zero_item(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : accepté, et ce n'est pas un échec."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        recu = await depot.depose(_document([]))
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert (ligne["state"], ligne["items_read"]) == (STATE_PROCESSED, 0)
        assert await depot.lignes() == {}


async def test_un_decoupage_qui_ne_designe_pas_un_tableau_echoue_sans_rien_ecrire(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : l'erreur nomme le jpath, et l'import se termine en échec."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        recu = await depot.depose(json.dumps({"magasins": {"M-1": _item("M-1")}}).encode())
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["state"] == STATE_FAILED_IMPORT
        assert ligne["failure_code"] == ITEMS_PATH_NOT_ARRAY
        assert ligne["failure_detail"] == "$.magasins[*]"
        assert await depot.lignes() == {}


async def test_un_decoupage_absent_du_document_echoue_en_le_nommant(
    blank_db: str, tmp_path: Path
) -> None:
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        recu = await depot.depose(json.dumps({"autre": [_item("M-1")]}).encode())
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert (ligne["state"], ligne["failure_code"]) == (STATE_FAILED_IMPORT, ITEMS_PATH_ABSENT)
        assert await depot.lignes() == {}


async def test_une_transaction_unifiee_n_ecrit_RIEN_d_un_document_tronque(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7 : ni corps ni date de dernière vue, et le nombre d'items lus est dit."""
    async with _ouvre(blank_db, tmp_path, transaction_unifiee=True) as (stack, depot):
        entier = _document([_item("M-1"), _item("M-2"), _item("M-3")])
        recu = await depot.depose(entier[: entier.index(b'"M-3"')])
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["state"] == STATE_FAILED_IMPORT
        assert ligne["failure_code"] == "document_json_invalide"
        # Les deux premiers items avaient été LUS : c'est l'information exploitable, et
        # c'est ce qui distingue « échoué » de « échoué après deux items ».
        assert ligne["items_read"] == 2
        assert await depot.lignes() == {}
        assert await depot.staging() == 0


async def test_sans_transaction_unifiee_un_document_tronque_laisse_un_import_incomplet(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8 : les items valides lus avant l'incident sont écrits, et l'état le dit.

    C'est cet état que le balayage refuse : confondu avec un import réussi, il ferait
    sortir du storage les objets que le document n'avait pas eu le temps de nommer.
    """
    async with _ouvre(blank_db, tmp_path, transaction_unifiee=False) as (stack, depot):
        entier = _document([_item("M-1"), _item("M-2"), _item("M-3")])
        recu = await depot.depose(entier[: entier.index(b'"M-3"')])
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["state"] == STATE_PARTIAL
        assert ligne["failure_code"] == "document_json_invalide"
        assert ligne["items_read"] == 2
        assert set(await depot.lignes()) == {M1, M2}


async def test_deux_items_de_meme_cle_sont_signales_et_le_dernier_gagne(
    blank_db: str, tmp_path: Path
) -> None:
    """Le dernier valide gagne — c'est l'ordre d'écriture —, et la source l'apprend."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        items = [_item("M-1", ville="Paris"), _item("M-1", ville="Lille")]
        recu = await depot.depose(_document(items))
        await stack.resolve_imports()

        rapport = json.loads((await depot.ingestion(recu.json()["id"]))["report"])
        assert rapport["anomalies"] == [f"{ANOMALY_DUPLICATE_KEY}:{M1}"]
        assert (await depot.lignes())[M1]["ville"] == "Lille"


async def test_un_rejeu_sous_la_meme_cle_d_idempotence_ne_repose_pas_le_document(
    blank_db: str, tmp_path: Path
) -> None:
    """Un acquittement perdu est un régime normal : le même accusé, et un seul import."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        corps = _document([_item("M-1")])
        premier = await depot.depose(corps, idempotence="lot-42")
        rejeu = await depot.depose(corps, idempotence="lot-42")
        await stack.resolve_imports()

        assert premier.status_code == 202
        assert rejeu.status_code == 200
        assert rejeu.json()["id"] == premier.json()["id"]
        assert rejeu.json()["replayed"] is True
        row = await stack.pool.fetchrow("SELECT count(*) AS n FROM ingestions")
        assert int(row["n"]) == 1


async def test_un_flux_d_octets_est_accepte_et_un_formulaire_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Écart volontaire avec les modes synchrones : un outil qui pousse un fichier
    n'annonce souvent rien de mieux qu'un flux d'octets."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        accepte = await depot.depose(_document([_item("M-1")]), content_type=OCTET_STREAM)
        refuse = await depot.depose(
            _document([_item("M-2")]), content_type="application/x-www-form-urlencoded"
        )

        assert accepte.status_code == 202, accepte.text
        assert refuse.status_code == 415
        assert refuse.json()["detail"]["code"] == "type_de_contenu_inattendu"


async def test_une_cle_sans_octroi_sur_la_source_ne_depose_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """La route vit HORS du portillon : elle s'authentifie elle-même, avant tout octet."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        refuse = await stack.anonymous().post(
            INGEST_FILE_PATH.format(source=SOURCE),
            content=_document([_item("M-1")]),
            headers={"X-API-Key": "mi_inexistante", "Content-Type": "application/json"},
        )

        assert refuse.status_code == 401
        assert refuse.json()["detail"]["code"] == "authentification_requise"
        assert await depot.stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0
        # Et surtout : aucun fichier n'a été posé sur le disque.
        assert await stack.ingestion_files.file_names() == set()


async def test_une_retention_nulle_ote_le_document_des_la_fin_de_l_import(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 20 : configuration valide, et le rejeu devient impossible — c'est dit."""
    async with _ouvre(blank_db, tmp_path, retention_days=0) as (stack, depot):
        recu = await depot.depose(_document([_item("M-1")]))
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["state"] == STATE_PROCESSED
        # L'historique RESTE, et il porte que le document n'est plus disponible.
        assert ligne["file_purged_at"] is not None
        assert await stack.ingestion_files.file_names() == set()


async def test_les_trois_instants_de_l_import_sont_ordonnes(blank_db: str, tmp_path: Path) -> None:
    """Critère 9, premier temps : la transaction d'écriture s'ouvre APRÈS la préparation.

    L'ordre seul ne dit pas qu'elle est courte — la mesure des durées est dans le test du
    régime établi — mais il dit que le parsing et la transformation sont HORS d'elle, ce
    qui est l'interdit du ticket.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        recu = await depot.depose(_document([_item(f"M-{n}") for n in range(1, 20)]))
        await stack.resolve_imports()

        ligne = await depot.ingestion(recu.json()["id"])
        assert ligne["started_at"] <= ligne["apply_started_at"] <= ligne["finished_at"]
