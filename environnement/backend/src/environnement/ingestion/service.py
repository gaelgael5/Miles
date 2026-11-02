"""Recevoir un dépôt, le persister, en accuser réception. Rien de plus à ce stade.

**L'accusé dit que le lot est REÇU, pas qu'il est écrit.** La transformation et l'écriture
différentielle sont le ticket suivant, et c'est délibéré : la trace de ce qui est
réellement arrivé doit exister AVANT qu'on y touche, sans quoi un résultat contesté n'est
pas reproductible et un incident de transformation n'est pas rejouable.

**L'ordre des contrôles n'est pas indifférent.** On authentifie avant de dire quoi que ce
soit de la version servie : sans cela, un appelant anonyme apprendrait quelles sources
existent, et dans quels modes, en lisant les refus.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

# L'annuaire d'auteur `apikey` vient du socle : une clé n'est pas une personne, et le
# journal doit le dire de la même façon dans les deux produits.
from miles_socle.apikeys.model import KEY_DIRECTORY
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.parametrage.sources import NAME_RE

from environnement.apikeys.model import KeyPrincipal
from environnement.apikeys.service import ApiKeysService
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.store import db_get_hosted_version
from environnement.ingestion.model import (
    CONTENT_TYPE,
    INGESTION_OBJECT_KIND,
    RECEIVED_EVENT,
    REFUSAL_AUCUNE_VERSION,
    REFUSAL_TYPE_DE_CONTENU,
    STATE_RECEIVED,
    Acknowledgement,
    IngestionRefusal,
    Target,
)
from environnement.ingestion.resolve import objects_of, target_of
from environnement.ingestion.store import db_ingestion_by_idempotency, db_record_ingestion
from environnement.sources.declarations import file_declared_sources

log = structlog.get_logger(__name__)
# La clé d'idempotence vient du réseau et sert de clé d'unicité : validée avant tout
# usage, comme toute entrée utilisateur.
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class NotAuthenticated(Exception):
    """Un seul refus pour toutes les raisons : forme, clé inconnue, révoquée, sans octroi.

    Les distinguer offrirait un oracle — savoir qu'une clé existe, ou qu'une source est
    déclarée. La raison précise est au journal, où elle sert au diagnostic.
    """


@dataclass(frozen=True)
class IngestionService:
    pool: asyncpg.Pool
    tree: HostedTree
    keys: ApiKeysService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_deposit(
        self,
        *,
        source: str,
        mode: str,
        presented: str | None,
        content_type: str | None,
        body: bytes,
        idempotency_key: str | None,
    ) -> Acknowledgement:
        """Reçoit un lot sur l'entrée que l'adresse désigne, et rend son accusé."""
        principal = await self._caller(source, mode, presented)
        if not _is_json(content_type):
            raise IngestionRefusal(REFUSAL_TYPE_DE_CONTENU, content_type or "")
        if idempotency_key is not None and not IDEMPOTENCY_RE.match(idempotency_key):
            # Elle devient une clé d'unicité en base : validée avant tout usage.
            raise IngestionRefusal("cle_idempotence_invalide")
        cible = target_of(await self._declared(), source, mode)
        objets = objects_of(mode, body)
        return await self._persist(cible, principal, objets, len(body), idempotency_key)

    async def _caller(self, source: str, mode: str, presented: str | None) -> KeyPrincipal:
        """L'appelant, ou un refus unique. **Avant toute lecture de la version servie.**"""
        if not NAME_RE.match(source):
            # Validé avant tout usage en chemin de fichier ou en identifiant. Et refusé
            # comme une clé invalide : un nom mal formé n'apprend rien de plus à
            # l'appelant que « tu n'entres pas ».
            log.info("depot_refuse", raison="source_mal_formee", mode=mode)
            raise NotAuthenticated
        principal = await self.keys.resolve_authenticate(presented, source)
        if principal is None:
            # La raison précise est déjà au journal, écrite par le vérificateur.
            raise NotAuthenticated
        return principal

    async def _declared(self) -> Any:
        paths = await self.tree.file_paths()
        return await file_declared_sources(self.tree.file_text, paths)

    async def _persist(
        self,
        cible: Target,
        principal: KeyPrincipal,
        objets: list[dict[str, object]],
        size_bytes: int,
        idempotency_key: str | None,
    ) -> Acknowledgement:
        version = await self._version_number()
        async with self.pool.acquire() as conn, conn.transaction():
            if idempotency_key is not None:
                deja = await db_ingestion_by_idempotency(conn, principal.key_id, idempotency_key)
                if deja is not None:
                    # Rien n'est persisté une seconde fois, et le MÊME accusé est rendu.
                    # Refuser serait pire : une ré-émission légitime, dont l'acquittement
                    # s'est perdu, est un régime normal, pas un incident.
                    log.info("depot_rejoue", ingestion=deja.id, key=principal.key_id)
                    return deja
            accuse = await db_record_ingestion(
                conn,
                ingestion_id=uuid.uuid4().hex,
                source=cible.source,
                entry_model=cible.entry.source_model,
                mode=cible.mode,
                version_number=version,
                key_id=principal.key_id,
                key_label=principal.label,
                now=self.now(),
                size_bytes=size_bytes,
                objects=objets,
                state=STATE_RECEIVED,
                idempotency_key=idempotency_key,
            )
            await self._journalise(conn, accuse, cible, principal)
        log.info(
            "depot_recu",
            ingestion=accuse.id,
            source=cible.source,
            mode=cible.mode,
            objets=accuse.object_count,
            key=principal.key_id,
        )
        return accuse

    async def _version_number(self) -> int:
        """La version que porte la stack. Sans elle, on ne reçoit pas.

        C'est ce qui rend un résultat contesté reproductible (critère 11) : savoir CONTRE
        QUOI le lot a été reçu. Une stack sans version n'a d'ailleurs aucune source
        déclarée, donc aucun point d'entrée — le refus ne ferme rien qui fût ouvert.
        """
        hebergee = await db_get_hosted_version(self.pool)
        if hebergee is None:
            raise IngestionRefusal(REFUSAL_AUCUNE_VERSION)
        return hebergee.ordered_number

    async def _journalise(
        self,
        conn: Any,
        accuse: Acknowledgement,
        cible: Target,
        principal: KeyPrincipal,
    ) -> None:
        # Dans la MÊME transaction que l'écriture du lot : aucun fait observable sans sa
        # trace, et jamais dans deux transactions (règle du système).
        #
        # L'auteur est la CLÉ, pas une personne : l'annuaire `apikey` le dit, et c'est ce
        # qui permet de relire plus tard « qui a déposé » sans emprunter l'identité de
        # l'administrateur qui a émis la clé.
        auteur = EventAuthor(KEY_DIRECTORY, principal.key_id)
        proprietes: dict[str, Any] = {
            "source": cible.source,
            "mode": cible.mode,
            "entry_model": cible.entry.source_model,
            "object_count": accuse.object_count,
            "key_label": principal.label,
        }
        event = NewEvent(
            RECEIVED_EVENT,
            (ObjectRef(INGESTION_OBJECT_KIND, accuse.id),),
            auteur,
            proprietes,
        )
        await db_write_event(conn, event, self.catalog, self.now)


def _is_json(content_type: str | None) -> bool:
    """Le type de contenu attendu, paramètres admis (`; charset=utf-8`).

    Exigé plutôt que deviné : un client qui poste un formulaire ou du XML doit l'apprendre
    de nous, pas d'une erreur d'analyse syntaxique qui parlerait d'une accolade.
    """
    if content_type is None:
        return False
    return content_type.split(";")[0].strip().lower() == CONTENT_TYPE
