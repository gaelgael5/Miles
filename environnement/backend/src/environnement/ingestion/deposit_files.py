"""Déposer un FICHIER : authentifier, borner, poser sur le disque, mettre en file.

**Ce dépôt n'accuse que la PRISE EN CHARGE**, et c'est ce que le contrat publié promet au
mode `fichier`. Il ne transforme rien et n'écrit dans aucun storage : l'import se déroule
ensuite (`fileimport.py`), et son issue se lit dans l'historique des ingestions.

**L'ordre des gestes est la garantie.** On authentifie, puis on vérifie que la version
servie permet ce dépôt, puis on vérifie que le disque peut l'accueillir — et seulement
alors on lit le corps. Lire d'abord aurait coûté le transfert d'un gigaoctet pour le
refuser à l'arrivée (critère 18), et aurait appris à un appelant anonyme quelles sources
existent.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.apikeys.model import KEY_DIRECTORY
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.transform.jpath import SplitRefusal, read_stream_split

from environnement.apikeys.model import KeyPrincipal
from environnement.apikeys.service import ApiKeysService
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.store import db_get_hosted_version
from environnement.ingestion.deposits import accepts_file, resolve_caller
from environnement.ingestion.files import DepositedFiles
from environnement.ingestion.importtarget import FAILURE_SPLIT
from environnement.ingestion.model import (
    FILE,
    INGESTION_OBJECT_KIND,
    RECEIVED_EVENT,
    REFUSAL_AUCUNE_VERSION,
    REFUSAL_CIBLE_NON_SERVIE,
    REFUSAL_TYPE_DE_CONTENU,
    Acknowledgement,
    IngestionRefusal,
    Target,
)
from environnement.ingestion.outcome import STATE_QUEUED
from environnement.ingestion.resolve import target_of
from environnement.ingestion.service import IDEMPOTENCY_RE
from environnement.ingestion.store import db_ingestion_by_idempotency
from environnement.ingestion.store_imports import db_record_file_deposit
from environnement.sources.declarations import file_declared_sources

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FileDeposits:
    pool: asyncpg.Pool
    tree: HostedTree
    keys: ApiKeysService
    files: DepositedFiles
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_deposit(
        self,
        *,
        source: str,
        presented: str | None,
        content_type: str | None,
        declared_length: int | None,
        chunks: AsyncIterator[bytes],
        idempotency_key: str | None,
    ) -> Acknowledgement:
        """Prend en charge un document déposé, et rend son accusé.

        `chunks` n'est consommé qu'après tous les refus : c'est ce qui fait qu'un dépôt
        impossible ne coûte ni transfert ni disque.
        """
        principal = await resolve_caller(self.keys, source, FILE, presented)
        if not accepts_file(content_type):
            raise IngestionRefusal(REFUSAL_TYPE_DE_CONTENU, content_type or "")
        if idempotency_key is not None and not IDEMPOTENCY_RE.match(idempotency_key):
            # Elle devient une clé d'unicité en base : validée avant tout usage.
            raise IngestionRefusal("cle_idempotence_invalide")
        deja = await self._replayed(principal, idempotency_key)
        if deja is not None:
            # Rejeu : le même accusé, et le document n'est PAS reposé sur le disque. Une
            # ré-émission dont l'acquittement s'est perdu est un régime normal.
            log.info("depot_fichier_rejoue", ingestion=deja.id, key=principal.key_id)
            return deja
        version = await self._version_number()
        cible = await self._target(source)
        await self.files.resolve_room_for(declared_length)
        return await self._store(cible, principal, chunks, version, idempotency_key)

    async def _replayed(
        self, principal: KeyPrincipal, idempotency_key: str | None
    ) -> Acknowledgement | None:
        if idempotency_key is None:
            return None
        async with self.pool.acquire() as conn:
            return await db_ingestion_by_idempotency(conn, principal.key_id, idempotency_key)

    async def _target(self, source: str) -> Target:
        """L'entrée que ce dépôt vise, et son découpage, vérifiés AVANT toute écriture.

        Le découpage est confronté au profil ici ALORS QUE l'import le refera : un refus à
        la prise en charge est synchrone, donc l'appelant l'apprend tout de suite, au lieu
        de découvrir dans un historique qu'un import a échoué sur un paramétrage fautif.
        Et l'import doit le refaire quand même — rien ne garantit que la déclaration soit
        la même quand il s'exécute.
        """
        paths = await self.tree.file_paths()
        declarees = await file_declared_sources(self.tree.file_text, paths)
        cible = target_of(declarees, source, FILE)
        lu = read_stream_split(cible.entry.split)
        if isinstance(lu, SplitRefusal):
            raise IngestionRefusal(REFUSAL_CIBLE_NON_SERVIE, f"{FAILURE_SPLIT}:{lu.code}")
        return cible

    async def _version_number(self) -> int:
        """La version que porte la stack. Sans elle, on ne reçoit pas.

        Elle est rangée sur l'ingestion, et l'import REFUSERA de s'exécuter si la stack
        sert autre chose entre-temps : appliquer un paramétrage que le déposant n'a jamais
        vu rendrait son résultat irreproductible.
        """
        hebergee = await db_get_hosted_version(self.pool)
        if hebergee is None:
            raise IngestionRefusal(REFUSAL_AUCUNE_VERSION)
        return hebergee.ordered_number

    async def _store(
        self,
        cible: Target,
        principal: KeyPrincipal,
        chunks: AsyncIterator[bytes],
        version: int,
        idempotency_key: str | None,
    ) -> Acknowledgement:
        """Pose le document, puis inscrit l'import dans la file.

        **Le fichier est posé AVANT la ligne**, et c'est un choix : l'inscrire d'abord
        aurait mis en file un import dont le document peut encore être refusé pour taille
        ou quota, et il aurait fallu défaire la ligne. Un arrêt entre les deux laisse un
        fichier sans ligne, que l'entretien reconnaît comme orphelin et ôte — alors qu'une
        ligne sans fichier aurait fait échouer un import pour une raison qui n'en est pas
        une.
        """
        ingestion_id = uuid.uuid4().hex
        pose = await self.files.resolve_receive(ingestion_id, chunks)
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            accuse = await db_record_file_deposit(
                conn,
                ingestion_id=ingestion_id,
                source=cible.source,
                entry_model=cible.entry.source_model,
                storage=cible.storage,
                version_number=version,
                key_id=principal.key_id,
                key_label=principal.label,
                now=maintenant,
                size_bytes=pose.size_bytes,
                file_name=pose.name,
                state=STATE_QUEUED,
                idempotency_key=idempotency_key,
            )
            await self._journalise(conn, accuse, cible, principal, pose.size_bytes)
        log.info(
            "depot_fichier_pris_en_charge",
            ingestion=accuse.id,
            source=cible.source,
            storage=cible.storage,
            octets=pose.size_bytes,
            key=principal.key_id,
        )
        return accuse

    async def _journalise(
        self,
        conn: Any,
        accuse: Acknowledgement,
        cible: Target,
        principal: KeyPrincipal,
        size_bytes: int,
    ) -> None:
        # Dans la MÊME transaction que l'inscription : aucun fait observable sans sa trace,
        # règle du système. L'auteur est la CLÉ, pas une personne.
        event = NewEvent(
            RECEIVED_EVENT,
            (ObjectRef(INGESTION_OBJECT_KIND, accuse.id),),
            EventAuthor(KEY_DIRECTORY, principal.key_id),
            {
                "source": cible.source,
                "mode": FILE,
                "entry_model": cible.entry.source_model,
                "storage": cible.storage,
                "size_bytes": size_bytes,
                "key_label": principal.label,
            },
        )
        await db_write_event(conn, event, self.catalog, self.now)
