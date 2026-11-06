"""Transformer les objets d'un lot et les écrire en différentiel. Le cœur de `d680e811`.

**Chaque objet est indépendant** (décision de Gael du 02/11/2026) : celui qui est fautif
est rejeté seul, les autres sont écrits. L'échec du LOT n'existe que si TOUT a été rejeté,
et alors rien n'est modifié — `vu_le` compris (critère 12), ce que la transaction unique de
l'appelant garantit.

**Deux objets de même clé dans un même lot** : le dernier gagne, à condition que son format
d'entrée soit valide (même décision). C'est ce que l'ordre d'écriture produit naturellement
— chaque écriture écrase la précédente —, et le compte-rendu le SIGNALE comme une anomalie
de source plutôt que de l'écrire en silence (critère 8).

**Un event par objet écrit** (Gael, 03/11/2026, contre la piste « un event par lot » du
cadrage). Un objet INCHANGÉ n'en produit pas : il n'y a pas eu de modification, et la règle
est « toute modification produit un event ». C'est le DELTA constaté qui parle, jamais le
fait que le code ait tourné — leçon du 02/11/2026 sur les opérations idempotentes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog
from miles_socle.events.journal import EventDb, db_write_events
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.parametrage.layout import MODEL_RE
from miles_socle.parametrage.refs import ReadFile
from miles_socle.transform.chain import Chain

from environnement.ingestion.chains import ChainUnreadable, file_load_chain
from environnement.ingestion.conformance import model_validator
from environnement.ingestion.keys import KeyRule, key_rule
from environnement.ingestion.outcome import (
    ANOMALY_DUPLICATE_KEY,
    REJECT_MANUAL,
    REJECTED,
    UNCHANGED,
    WRITTEN,
    ObjectOutcome,
    Report,
)
from environnement.ingestion.preparation import prepare_object
from environnement.ingestion.store_merge import MergeDb, MergedObject, db_merge_items
from environnement.storages.declarations import file_declared, file_model_schema
from environnement.storages.model import StorageTable

log = structlog.get_logger(__name__)

OBJECT_WRITTEN_EVENT = "environment.storage_object_written"
EVENT_TYPES = frozenset({OBJECT_WRITTEN_EVENT})


class ProcessingDb(MergeDb, EventDb, Protocol):
    """La connexion du traitement : elle fusionne les objets ET écrit leurs events.

    Les deux protocoles réunis plutôt que l'un des deux élargi : la fusion n'a besoin que
    de `fetch`, l'event demande en plus un point de sauvegarde, et chacun des deux modules
    reste éprouvable avec une doublure de ce qu'il demande seulement. Ce qui est commun, et
    qui est le point, est que c'est la MÊME connexion.
    """


class NotServed(Exception):
    """Ce que l'entrée désigne n'est pas servi par la version en place : storage, modèle
    ou chaîne.

    **Résolu AVANT de persister le lot**, et c'est un choix. Ce n'est pas le rejet d'un
    objet : aucun objet de ce lot ne pourrait aboutir, et persister un dépôt pour rejeter
    ensuite ses deux cents objets un par un donnerait un compte-rendu qui répète deux
    cents fois la même faute de paramétrage. C'est un refus de DÉPÔT, de la même famille
    que « mode non déclaré » — la version servie ne permet pas cet appel.

    La règle « le lot est persisté avant toute transformation » est intacte : rien n'est
    transformé ici, on se contente de lire ce que la version déclare.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Prepared:
    """Ce que la version servie offre pour cette entrée, TOUT COMPILÉ : table, modèle,
    chaîne, règle de clé.

    Résolu une fois par dépôt, et non par objet : les trois premiers viennent de l'arbre
    git, et les relire deux cents fois coûterait deux cents lectures de fichiers pour un
    résultat qui ne peut pas changer pendant un dépôt.

    La RÈGLE DE CLÉ est ici depuis le 06/11/2026, et pour la même raison, qui est juste
    arrivée plus tard : son jpath était recompilé à chaque objet — 372,5 µs mesurés, 70 %
    du temps de préparation d'un item, quatre fois le prix du template JSLT. Le `schema`
    se lit par `validator.schema` : une seule source, et pas deux champs à tenir d'accord.
    """

    table: StorageTable
    validator: Any
    chain: Chain
    keys: KeyRule


async def file_prepare(read: ReadFile, paths: list[str], storage: str, chain_slug: str) -> Prepared:
    """Lit la table, le modèle et la chaîne, et COMPILE tout ce qui se compile.

    Lève `NotServed` en nommant ce qui manque.
    """
    table = await _table(read, paths, storage)
    schema = await _schema(read, table)
    try:
        chain = await file_load_chain(read, chain_slug)
    except ChainUnreadable as refus:
        raise NotServed(f"chaine:{refus.detail}") from None
    return Prepared(table, model_validator(schema), chain, key_rule(table.keys))


@dataclass(frozen=True)
class Processing:
    """Ce qu'il faut pour ÉCRIRE un lot préparé. Tout est injecté : rien d'un global.

    `db` est typée par le protocole du JOURNAL, qui est le plus exigeant des deux usages :
    l'écriture d'un objet n'a besoin que de `fetchrow`, l'event demande en plus un point
    de sauvegarde. Les deux partent sur la MÊME connexion, dans la même transaction — un
    fait observable sans sa trace est interdit par le système.
    """

    db: ProcessingDb
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    budget: int
    author: EventAuthor
    ingestion_id: str
    model_version: int


async def resolve_process(
    processing: Processing, prepared: Prepared, objets: list[dict[str, object]]
) -> Report:
    """Prépare tout le lot, le fusionne d'un geste, et rend son compte-rendu.

    **La préparation est séparée de l'écriture, même ici.** Les deux cents objets d'un
    appel sont d'abord transformés — hors de toute instruction —, puis écrits par UNE
    fusion ensembliste (Gael, 06/11/2026). Les écrire un par un faisait deux cents
    allers-retours pour un lot que la base sait prendre en une fois ; et c'est le même
    code de fusion que celui qu'un import de cinquante mille items emprunte, donc la
    règle de l'objet d'origine manuelle n'existe qu'en un exemplaire.

    L'ordre des trois contrôles de la préparation n'est pas indifférent. La TRANSFORMATION
    d'abord, parce que tout le reste porte sur son résultat. Puis le MODÈLE, parce qu'une
    propriété de clé absente est le plus souvent une violation du modèle, et « modèle non
    respecté, à tel chemin » envoie corriger le template là où « clé non extractible »
    laisse chercher. La CLÉ en dernier, sur un objet dont on sait déjà qu'il a la forme
    attendue.
    """
    items = [
        prepare_object(
            prepared.chain,
            prepared.validator,
            prepared.keys,
            rang,
            source,
            processing.budget,
        )
        for rang, source in enumerate(objets)
    ]
    fusionnes = await db_merge_items(
        processing.db,
        prepared.table,
        items,
        now=processing.now(),
        model_version=processing.model_version,
    )
    par_rang = {merged.position: merged for merged in fusionnes}
    report = Report(received=len(objets))
    vues: dict[str, int] = {}
    ecrits: list[tuple[str, bool]] = []
    for item in items:
        merged = par_rang.get(item.position)
        issue = item.rejection() if merged is None else written_outcome(merged)
        report.objects.append(issue)
        if merged is not None and merged.result.written:
            ecrits.append((merged.key, merged.result.created))
        if issue.key is not None and issue.outcome != REJECTED:
            if issue.key in vues:
                report.anomalies.append(f"{ANOMALY_DUPLICATE_KEY}:{issue.key}")
            vues[issue.key] = item.position
    await resolve_written_events(processing, prepared.table, ecrits)
    return report


async def _table(read: ReadFile, paths: list[str], storage: str) -> StorageTable:
    declared = await file_declared(read, paths)
    for table in declared.tables:
        if table.storage == storage:
            return table
    # Le MOTIF du refus quand la déclaration existe et est fautive : « storage absent »
    # sur un storage déclaré mais refusé enverrait le chercher là où il est.
    refus = next((r for r in declared.refusals if r.storage == storage), None)
    raise NotServed(
        f"storage:{storage}:{refus.code}" if refus is not None else f"storage:{storage}"
    )


async def _schema(read: ReadFile, table: StorageTable) -> Any:
    designation = MODEL_RE.match(table.model)
    if designation is None:
        raise NotServed(f"modele:{table.model}")
    schema = await file_model_schema(read, designation["scope"], designation["name"])
    if schema is None:
        raise NotServed(f"modele:{table.model}")
    return schema


def written_outcome(merged: MergedObject) -> ObjectOutcome:
    """Le sort d'un objet fusionné, pour le compte-rendu.

    **Une seule copie de cette correspondance**, empruntée par les deux modes : « refusé
    parce que manuel » est une règle, et deux traductions du même verdict auraient fini
    par nommer deux choses différentes dans deux compte-rendus.
    """
    if merged.result.refused:
        return ObjectOutcome(merged.position, REJECTED, merged.key, REJECT_MANUAL)
    if merged.result.written:
        return ObjectOutcome(merged.position, WRITTEN, merged.key)
    return ObjectOutcome(merged.position, UNCHANGED, merged.key)


async def resolve_written_events(
    processing: Processing, table: StorageTable, ecrits: list[tuple[str, bool]]
) -> None:
    """Un event par objet ÉCRIT, tous dans UNE instruction, dans la transaction du lot.

    Dans la même transaction que l'écriture : aucun fait observable sans sa trace, règle
    du système. L'objet concerné est désigné par son storage et sa clé — pas par
    l'identifiant de ligne, qui ne survit pas à une recréation.

    **Un event par objet et non un par lot** (Gael, 03/11/2026, contre la piste du
    cadrage) : ce qui a changé le 06/11/2026 n'est pas la règle, c'est son coût — trois
    allers-retours par event faisaient cent cinquante mille instructions pour cinquante
    mille objets, là où `db_write_events` en fait trois pour tout le lot.
    """
    if not ecrits:
        return
    events = [
        NewEvent(
            OBJECT_WRITTEN_EVENT,
            (ObjectRef(table.storage, cle),),
            processing.author,
            {
                "storage": table.storage,
                "created": created,
                "ingestion": processing.ingestion_id,
                "model": table.model,
            },
        )
        for cle, created in ecrits
    ]
    await db_write_events(processing.db, events, processing.catalog, processing.now)
