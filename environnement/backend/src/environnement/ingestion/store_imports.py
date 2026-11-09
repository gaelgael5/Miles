"""Les requêtes de la FILE et de l'exécution d'un import de fichier. Rien ne décide ici.

À part de `store.py`, qui porte le dépôt et son accusé : ici, ce qui n'existe que parce
que l'import d'un fichier est ASYNCHRONE — la file, la prise, les instants, l'issue, et la
conservation du document déposé (story `0f14adbd`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from environnement.ingestion.model import Acknowledgement
from environnement.ingestion.outcome import Report
from environnement.ingestion.store import IngestionDb, ack_of

_SELECT = "SELECT id, source, mode, object_count, received_at, state, report FROM ingestions"


@dataclass(frozen=True)
class ImportJob:
    """Un import pris : de quoi le mener sans rien relire d'autre que l'arbre servi.

    `version_number` est celui du DÉPÔT. Il est gardé parce que l'import a lieu plus tard :
    si la stack sert depuis une autre version, le paramétrage qui a autorisé ce dépôt n'est
    plus là, et l'import doit le dire plutôt que d'appliquer une chaîne que le déposant n'a
    jamais vue.
    """

    id: str
    source: str
    storage: str
    file_name: str
    size_bytes: int
    version_number: int
    key_id: str
    # L'instant où CET import a été pris, relu de la ligne qu'on vient d'écrire et non
    # recalculé par l'appelant. C'est la frontière du marquage des absents (story
    # `82bc9dca`) : tout ce que l'import porte voit son `vu_le` avancer au-delà. Deux
    # valeurs — celle posée en base et celle que l'horloge rendrait plus tard — auraient
    # laissé des items du bon côté de l'une et du mauvais côté de l'autre.
    started_at: datetime


@dataclass(frozen=True)
class KeptFile:
    """Un document déposé encore sur le disque, avec ce qu'il faut pour décider de sa purge."""

    ingestion_id: str
    file_name: str
    received_at: datetime
    size_bytes: int
    # L'import est-il encore en file ou en cours ? Un fichier dont l'import tourne ne se
    # purge JAMAIS, même sous pression de quota (critère 17).
    busy: bool


async def db_record_file_deposit(
    db: IngestionDb,
    *,
    ingestion_id: str,
    source: str,
    entry_model: str,
    storage: str,
    version_number: int,
    key_id: str,
    key_label: str,
    now: datetime,
    size_bytes: int,
    file_name: str,
    state: str,
    idempotency_key: str | None,
) -> Acknowledgement:
    """Enregistre la PRISE EN CHARGE d'un dépôt de fichier, et rend son accusé.

    `object_count` vaut zéro et non le nombre d'items : personne ne les a comptés, et le
    document n'est pas lu. Zéro dit « rien de traité », ce qui est exact ; une estimation
    aurait été un chiffre faux dans un accusé.
    """
    row = await db.fetchrow(
        "INSERT INTO ingestions (id, source, entry_model, mode, storage, version_number,"
        " key_id, key_label, received_at, size_bytes, object_count, state, idempotency_key,"
        " file_name)"
        " VALUES ($1, $2, $3, 'fichier', $4, $5, $6, $7, $8, $9, 0, $10, $11, $12)"
        " RETURNING id, source, mode, object_count, received_at, state, report",
        ingestion_id,
        source,
        entry_model,
        storage,
        version_number,
        key_id,
        key_label,
        now,
        size_bytes,
        state,
        idempotency_key,
        file_name,
    )
    return ack_of(row, replayed=False)


async def db_claim_next(db: IngestionDb, storage: str, now: datetime) -> ImportJob | None:
    """Prend le plus ancien import en file sur ce storage, ou rien.

    **Une seule instruction, et pas un SELECT puis un UPDATE** : entre les deux, deux
    processus prendraient le même import. `SKIP LOCKED` fait trancher la base, et la
    clause sur l'état garantit qu'un import déjà pris n'est pas repris — la skill
    PostgreSQL le dit, l'idempotence se joue à l'écriture.
    """
    row = await db.fetchrow(
        "UPDATE ingestions SET state = 'en_cours', started_at = $2 WHERE id = ("
        "  SELECT id FROM ingestions WHERE storage = $1 AND state = 'en_file'"
        "  ORDER BY received_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
        ") RETURNING id, source, storage, file_name, size_bytes, version_number, key_id,"
        " started_at",
        storage,
        now,
    )
    return None if row is None else _job(row)


async def db_queued_storages(db: IngestionDb) -> list[str]:
    """Les storages qui ont un import en attente. Sert au rattrapage de l'entretien."""
    rows = await db.fetch(
        "SELECT DISTINCT storage FROM ingestions WHERE state = 'en_file' AND storage IS NOT NULL"
    )
    return [row["storage"] for row in rows]


async def db_running_imports(db: IngestionDb) -> list[ImportJob]:
    """Les imports déclarés en cours. Un seul tourne par storage : les autres sont des
    orphelins qu'un service arrêté a laissés (critère 14)."""
    rows = await db.fetch(
        "SELECT id, source, storage, file_name, size_bytes, version_number, key_id"
        " FROM ingestions WHERE state = 'en_cours' ORDER BY received_at"
    )
    return [_job(row) for row in rows]


async def db_requeue(db: IngestionDb, ingestion_id: str) -> bool:
    """Remet un import orphelin dans la file. Rend faux s'il n'y était plus.

    Rejouer depuis le document conservé est sûr parce que l'écriture est DIFFÉRENTIELLE :
    un item déjà écrit par la tentative interrompue a la même empreinte, donc il ressort
    « inchangé », et seule sa date de dernière vue avance — ce qu'un import doit faire de
    toute façon.
    """
    rendu = await db.execute(
        "UPDATE ingestions SET state = 'en_file', started_at = NULL, apply_started_at = NULL"
        " WHERE id = $1 AND state = 'en_cours'",
        ingestion_id,
    )
    return rendu.endswith("1")


async def db_mark_applying(db: IngestionDb, ingestion_id: str, now: datetime) -> None:
    """Pose l'instant où la transaction d'écriture s'ouvre.

    C'est lui qui rend le critère 9 vérifiable : la durée de l'écriture se compare à la
    durée totale de l'import, et sans cet instant la comparaison n'existe pas.
    """
    await db.execute("UPDATE ingestions SET apply_started_at = $2 WHERE id = $1", ingestion_id, now)


async def db_set_metadata(db: IngestionDb, ingestion_id: str, metadata: Any | None) -> None:
    """Range les métadonnées du document (critère 6). Nulles : rien n'est écrit."""
    if metadata is None:
        return
    await db.execute(
        "UPDATE ingestions SET metadata = $2::jsonb WHERE id = $1",
        ingestion_id,
        json.dumps(metadata, ensure_ascii=False),
    )


async def db_finish_import(
    db: IngestionDb,
    ingestion_id: str,
    *,
    state: str,
    report: Report | None,
    items_read: int,
    now: datetime,
    failure_code: str | None = None,
    failure_detail: str | None = None,
) -> Acknowledgement:
    """Range l'issue de l'import, et rend l'accusé LU de la ligne écrite.

    Lu de la ligne et non reconstruit : un stockage normalise ce qu'on lui donne, et
    l'accusé doit dire ce qui est en base.
    """
    row = await db.fetchrow(
        "UPDATE ingestions SET state = $2, report = $3::jsonb, items_read = $4,"
        " object_count = $4, finished_at = $5, failure_code = $6, failure_detail = $7"
        " WHERE id = $1"
        " RETURNING id, source, mode, object_count, received_at, state, report",
        ingestion_id,
        state,
        None if report is None else json.dumps(report.as_json(), ensure_ascii=False),
        items_read,
        now,
        failure_code,
        failure_detail,
    )
    return ack_of(row, replayed=False)


async def db_kept_files(db: IngestionDb) -> list[KeptFile]:
    """Les documents encore sur le disque, du plus ancien au plus récent.

    Du plus ancien d'abord parce que c'est l'ordre de la purge : par ancienneté avant
    tout, et le quota ne change pas cet ordre (critère 17).
    """
    rows = await db.fetch(
        "SELECT id, file_name, received_at, size_bytes,"
        " state IN ('en_file', 'en_cours') AS busy"
        " FROM ingestions WHERE file_name IS NOT NULL AND file_purged_at IS NULL"
        " ORDER BY received_at, id"
    )
    return [
        KeptFile(
            ingestion_id=row["id"],
            file_name=row["file_name"],
            received_at=row["received_at"],
            size_bytes=int(row["size_bytes"] or 0),
            busy=bool(row["busy"]),
        )
        for row in rows
    ]


async def db_mark_file_purged(db: IngestionDb, ingestion_id: str, now: datetime) -> None:
    """Dit que le document n'est plus disponible, SANS toucher à l'historique (critère 16).

    L'historique ne disparaît jamais avec le fichier : on doit pouvoir lire des mois plus
    tard qu'un import a eu lieu, et pourquoi son document ne peut plus être rejoué.
    """
    await db.execute(
        "UPDATE ingestions SET file_purged_at = $2 WHERE id = $1 AND file_purged_at IS NULL",
        ingestion_id,
        now,
    )


async def db_ingestion_file(db: IngestionDb, ingestion_id: str) -> KeptFile | None:
    """Le document d'un import précis, s'il est encore là."""
    row = await db.fetchrow(
        "SELECT id, file_name, received_at, size_bytes,"
        " state IN ('en_file', 'en_cours') AS busy"
        " FROM ingestions WHERE id = $1 AND file_name IS NOT NULL AND file_purged_at IS NULL",
        ingestion_id,
    )
    if row is None:
        return None
    return KeptFile(
        ingestion_id=row["id"],
        file_name=row["file_name"],
        received_at=row["received_at"],
        size_bytes=int(row["size_bytes"] or 0),
        busy=bool(row["busy"]),
    )


def _job(row: Any) -> ImportJob:
    return ImportJob(
        id=row["id"],
        source=row["source"],
        storage=row["storage"],
        file_name=row["file_name"],
        size_bytes=int(row["size_bytes"] or 0),
        version_number=int(row["version_number"]),
        key_id=row["key_id"],
        started_at=row["started_at"],
    )


async def db_storage_of(db: IngestionDb, ingestion_id: str) -> str | None:
    """Le storage de cette ingestion, relu de la LIGNE.

    Relu et non reçu en argument par l'appelant : c'est ce qui a été enregistré qui
    sérialise les imports, et le lancement doit porter sur la même valeur que la file.
    """
    row = await db.fetchrow("SELECT storage FROM ingestions WHERE id = $1", ingestion_id)
    return None if row is None else row["storage"]
