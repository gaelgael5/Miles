"""Recevoir un dépôt, le persister, le traiter, en rendre le compte-rendu.

**Le lot est persisté AVANT d'être transformé**, et l'ordre n'est pas négociable : sans la
trace de ce qui est réellement arrivé, un résultat contesté n'est pas reproductible et un
incident de transformation n'est pas rejouable. Les deux gestes sont dans la MÊME
transaction, et c'est ce qui rend la reprise sûre (critère 14) — un service interrompu au
milieu du traitement n'a rien laissé, ni lot ni écriture, et le même dépôt rejoué repart
de zéro sans doublon.

**Ce que la version servie ne porte pas est refusé avant toute persistance** : storage,
modèle ou chaîne absents sont de la famille « mode non déclaré », pas du rejet d'objet.
Aucun objet du lot ne pourrait aboutir, et persister pour rejeter deux cents fois la même
faute de paramétrage ne renseignerait personne.

**L'ordre des contrôles n'est pas indifférent.** On authentifie avant de dire quoi que ce
soit de la version servie : sans cela, un appelant anonyme apprendrait quelles sources
existent, et dans quels modes, en lisant les refus.
"""

from __future__ import annotations

import json
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
from miles_socle.events.catalog import EventCatalog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef

from environnement.apikeys.model import KeyPrincipal
from environnement.apikeys.service import ApiKeysService
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.store import db_get_hosted_version
from environnement.ingestion.deposits import accepts_json, resolve_caller
from environnement.ingestion.model import (
    INGESTION_OBJECT_KIND,
    RECEIVED_EVENT,
    REFUSAL_AUCUNE_VERSION,
    REFUSAL_CIBLE_NON_SERVIE,
    REFUSAL_TYPE_DE_CONTENU,
    STATE_RECEIVED,
    Acknowledgement,
    IngestionRefusal,
    Target,
)
from environnement.ingestion.outcome import STATE_FAILED, STATE_PROCESSED
from environnement.ingestion.resolve import objects_of, target_of
from environnement.ingestion.store import (
    db_ingestion_by_idempotency,
    db_mark_processed,
    db_record_ingestion,
)
from environnement.ingestion.writeback import (
    NotServed,
    Prepared,
    Processing,
    file_prepare,
    resolve_process,
)
from environnement.sources.declarations import file_declared_sources

log = structlog.get_logger(__name__)
# La clé d'idempotence vient du réseau et sert de clé d'unicité : validée avant tout
# usage, comme toute entrée utilisateur.
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


@dataclass(frozen=True)
class IngestionService:
    pool: asyncpg.Pool
    tree: HostedTree
    keys: ApiKeysService
    catalog: EventCatalog
    now: Callable[[], datetime]
    # Borne de l'évaluation d'un template. C'est un TIERS qui fournit le document ici,
    # pas l'auteur du template : sans borne, un document démesuré retiendrait le service.
    transform_budget: int

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
        principal = await resolve_caller(self.keys, source, mode, presented)
        if not accepts_json(content_type):
            raise IngestionRefusal(REFUSAL_TYPE_DE_CONTENU, content_type or "")
        if idempotency_key is not None and not IDEMPOTENCY_RE.match(idempotency_key):
            # Elle devient une clé d'unicité en base : validée avant tout usage.
            raise IngestionRefusal("cle_idempotence_invalide")
        paths = await self.tree.file_paths()
        cible = target_of(await self._declared(paths), source, mode)
        objets = objects_of(mode, body)
        # AVANT toute persistance : ce que la version servie n'offre pas se refuse comme
        # un mode non déclaré. Lu une fois pour le dépôt, jamais par objet.
        try:
            prepare = await file_prepare(
                self.tree.file_text, paths, cible.storage, cible.entry.chain
            )
        except NotServed as refus:
            raise IngestionRefusal(REFUSAL_CIBLE_NON_SERVIE, refus.detail) from None
        return await self._persist(cible, prepare, principal, objets, len(body), idempotency_key)

    async def _declared(self, paths: list[str]) -> Any:
        return await file_declared_sources(self.tree.file_text, paths)

    async def _persist(
        self,
        cible: Target,
        prepare: Prepared,
        principal: KeyPrincipal,
        objets: list[dict[str, object]],
        size_bytes: int,
        idempotency_key: str | None,
    ) -> Acknowledgement:
        version = await self._version_number()
        async with self.pool.acquire() as conn, conn.transaction():
            if idempotency_key is not None:
                deja = await db_ingestion_by_idempotency(conn, principal.key_id, idempotency_key)
                if deja is not None and deja.report is not None:
                    # Déjà TRAITÉ : le même accusé et le même compte-rendu. Refuser serait
                    # pire — une ré-émission légitime, dont l'acquittement s'est perdu, est
                    # un régime normal, pas un incident (critère 13).
                    log.info("depot_rejoue", ingestion=deja.id, key=principal.key_id)
                    return deja
                if deja is not None:
                    # Reçu mais JAMAIS traité : c'est ce qu'un service interrompu laisse
                    # derrière lui. On reprend le traitement au lieu de rendre un
                    # compte-rendu vide — rien n'avait été écrit, donc ni doublon ni perte
                    # (critère 14). Le lot traité est celui de la base, pas celui du corps
                    # reçu : c'est la trace du premier dépôt qui fait foi.
                    log.info("depot_repris", ingestion=deja.id, key=principal.key_id)
                    return await self._process(conn, deja, cible, prepare, principal, version)
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
            return await self._process(conn, accuse, cible, prepare, principal, version)

    async def _process(
        self,
        conn: Any,
        accuse: Acknowledgement,
        cible: Target,
        prepare: Prepared,
        principal: KeyPrincipal,
        version: int,
    ) -> Acknowledgement:
        """Transforme et écrit les objets du lot persisté, puis range son compte-rendu.

        Les objets traités sont relus de la LIGNE d'ingestion et non du corps reçu : c'est
        la trace de ce qui est réellement arrivé qui fait foi, et c'est elle qu'une reprise
        retrouve. L'auteur de chaque event écrit est la CLÉ, jamais une personne.
        """
        objets = await _raw_objects(conn, accuse.id)
        processing = Processing(
            db=conn,
            catalog=self.catalog,
            now=self.now,
            budget=self.transform_budget,
            author=EventAuthor(KEY_DIRECTORY, principal.key_id),
            ingestion_id=accuse.id,
            model_version=version,
        )
        rapport = await resolve_process(processing, prepare, objets)
        # « rejete » dit que RIEN n'a abouti (critère 12). Aucune ligne de storage n'a
        # bougé pour autant, `vu_le` compris : chaque motif de rejet est décidé avant
        # d'écrire, et le seul qui atteigne la base — l'objet d'origine manuelle — est
        # écarté par la clause de l'instruction elle-même.
        etat = STATE_FAILED if rapport.all_rejected else STATE_PROCESSED
        log.info(
            "depot_traite",
            ingestion=accuse.id,
            source=cible.source,
            ecrits=rapport.written,
            inchanges=rapport.unchanged,
            rejetes=rapport.rejected,
        )
        return await db_mark_processed(conn, accuse.id, etat, rapport)

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


async def _raw_objects(conn: Any, ingestion_id: str) -> list[dict[str, object]]:
    """Le lot BRUT tel qu'il a été persisté. Une colonne jsonb revient en CHAÎNE."""
    row = await conn.fetchrow("SELECT raw FROM ingestions WHERE id = $1", ingestion_id)
    brut = row["raw"]
    objets = json.loads(brut) if isinstance(brut, str) else brut
    return list(objets)
