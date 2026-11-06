"""Appliquer l'aire de préparation à la table du storage : LA transaction courte.

**C'est ici que l'interdit du ticket `0f14adbd` se tient** : le parsing et la transformation
ont eu lieu avant, hors transaction, et il ne reste qu'à confronter des items déjà
transformés à la table. Sur un gros fichier, le temps n'est pas dans l'écriture mais dans
l'évaluation du template item par item ; une transaction ouverte plusieurs minutes empêche
autovacuum de nettoyer les versions mortes de la table que l'import malmène, et sur un
import quotidien le bloat s'installe.

**Ce qui rend la transaction unifiée supportable** : en régime établi elle est bon marché.
L'écriture différentielle fait qu'un import nominal ne touche qu'une poignée de lignes même
sur cinquante mille items — la grosse transaction n'arrive qu'au premier import et au
premier réimport après un changement de template, les deux moments où l'on sait déjà qu'on
fait une opération de masse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

from environnement.ingestion.outcome import (
    ANOMALY_DETAIL_CAPPED,
    ANOMALY_DUPLICATE_KEY,
    REJECTED,
    ObjectOutcome,
    Report,
)
from environnement.ingestion.staging import PreparedRow, db_duplicate_keys, db_prepared_window
from environnement.ingestion.store_merge import MERGE_WINDOW, db_merge_window
from environnement.ingestion.writeback import (
    Prepared,
    Processing,
    resolve_written_events,
    written_outcome,
)

log = structlog.get_logger(__name__)

# Dépassement du plafond de durée de l'écriture (critère 13).
FAILURE_APPLY_TOO_LONG = "ecriture_trop_longue"


class ApplyTooLong(Exception):
    """Le plafond de durée de la transaction d'écriture est dépassé.

    Levée DANS la transaction, donc elle l'annule : c'est le point du critère 13 — le
    dépassement termine l'import en échec plutôt que de laisser la transaction ouverte.
    """


@dataclass(frozen=True)
class ApplyPlan:
    """Ce que la déclaration de l'entrée demande à l'écriture.

    `unified` ne couvre que l'échec du DÉPÔT : le rejet d'un objet fautif ne fait pas
    tomber les autres (Gael, 02/11/2026). `write_batch` dit TOUS LES COMBIEN on écrit,
    `unified` dit QUAND on valide — les deux sont indépendants.
    """

    unified: bool
    write_batch: int
    seconds: float
    # Nombre de rejets gardés au compte-rendu. Au-delà, les comptes restent exacts et
    # l'anomalie dit que le détail est plafonné.
    detail_cap: int


async def resolve_apply(
    conn: Any, processing: Processing, prepared: Prepared, plan: ApplyPlan
) -> Report:
    """Écrit les items préparés et rend le compte-rendu du lot."""
    report = Report(received=0)
    if plan.unified:
        # Tout ou rien : une seule transaction pour l'import entier (critère 7).
        async with conn.transaction():
            await _bounded(conn, plan)
            await _drain(conn, processing, prepared, plan, report, time.monotonic())
    else:
        await _by_batch(conn, processing, prepared, plan, report)
    report.anomalies.extend(await _duplicates(conn, plan))
    log.info(
        "import_applique",
        ingestion=processing.ingestion_id,
        unifiee=plan.unified,
        ecrits=report.written,
        inchanges=report.unchanged,
        rejetes=report.rejected,
    )
    return report


async def _by_batch(
    conn: Any, processing: Processing, prepared: Prepared, plan: ApplyPlan, report: Report
) -> None:
    """Une transaction par lot d'écriture.

    C'est ce qui rend le critère 8 possible : un document interrompu laisse écrits les
    items valides lus avant l'incident, au lieu de tout perdre. L'import est alors marqué
    incomplet, et c'est cet état que le balayage refuse.
    """
    rang = -1
    while True:
        fenetre = await db_prepared_window(conn, after=rang, limit=plan.write_batch)
        if not fenetre:
            return
        debut = time.monotonic()
        async with conn.transaction():
            await _bounded(conn, plan)
            await _resolve_window(conn, processing, prepared, plan, report, fenetre, rang, debut)
        rang = fenetre[-1].position


async def _drain(
    conn: Any,
    processing: Processing,
    prepared: Prepared,
    plan: ApplyPlan,
    report: Report,
    debut: float,
) -> None:
    """Tous les items, dans la transaction ouverte par l'appelant.

    Lus par paquets et non d'un coup : l'aire de préparation peut porter cinquante mille
    items, et les charger tous rendrait en mémoire ce que la lecture en flux avait
    précisément évité de garder.
    """
    rang = -1
    while True:
        fenetre = await db_prepared_window(conn, after=rang, limit=plan.write_batch)
        if not fenetre:
            return
        await _resolve_window(conn, processing, prepared, plan, report, fenetre, rang, debut)
        rang = fenetre[-1].position


async def _resolve_window(
    conn: Any,
    processing: Processing,
    prepared: Prepared,
    plan: ApplyPlan,
    report: Report,
    fenetre: list[PreparedRow],
    after: int,
    debut: float,
) -> None:
    """Fusionne la fenêtre d'un geste, compte chaque rang, puis trace les objets écrits.

    **Les objets ne remontent jamais ici** : la fenêtre n'est lue qu'en métadonnées — rang,
    sort, motif de rejet — et c'est la fusion qui déplace les corps de la table temporaire
    vers celle du storage, à l'intérieur de la base (Gael, 06/11/2026). Les relire pour les
    renvoyer aussitôt aurait fait voyager deux fois cinquante mille documents.

    Les rejets, eux, sont décidés à la préparation et ne concernent pas la base : ils sont
    comptés depuis la fenêtre, dans l'ordre des rangs, pour que le plafond de détail garde
    bien les PREMIERS rejets du document.
    """
    # La fenêtre LUE est celle du `lot_ecriture`, qui dit tous les combien on valide ; les
    # instructions de fusion, elles, sont bornées à `MERGE_WINDOW` items, parce que leur
    # coût par item croît avec leur taille (mesure au point d'application). Les deux
    # réglages cessent ainsi de se confondre : un `lot_ecriture` de cinq mille allonge la
    # transaction, il ne fait plus tomber le plan.
    par_rang: dict[int, Any] = {}
    borne = after
    for depart in range(0, len(fenetre), MERGE_WINDOW):
        tranche = fenetre[depart : depart + MERGE_WINDOW]
        fusionnes = await db_merge_window(
            conn,
            prepared.table,
            after=borne,
            through=tranche[-1].position,
            now=processing.now(),
            model_version=processing.model_version,
        )
        par_rang |= {merged.position: merged for merged in fusionnes}
        borne = tranche[-1].position
    ecrits: list[tuple[str, bool]] = []
    for ligne in fenetre:
        _timed(debut, plan)
        if not ligne.writable:
            rejet = ObjectOutcome(ligne.position, REJECTED, ligne.key, ligne.reason, ligne.detail)
            report.counted(rejet, keep=plan.detail_cap)
            continue
        merged = par_rang.get(ligne.position)
        if merged is None:
            # Jamais de repli : un item écrivable que la fusion n'a pas rendu voudrait dire
            # que la fenêtre lue et la fenêtre fusionnée ne sont pas la même, et le
            # compte-rendu compterait un objet de moins que le document n'en porte.
            raise ValueError(f"rang {ligne.position} absent de la fusion de sa fenêtre")
        report.counted(written_outcome(merged), keep=plan.detail_cap)
        if merged.result.written:
            ecrits.append((merged.key, merged.result.created))
    await resolve_written_events(processing, prepared.table, ecrits)


async def _bounded(conn: Any, plan: ApplyPlan) -> None:
    """Borne la durée d'UNE instruction dans la transaction ouverte.

    En plus de la garde de durée totale, et pas à sa place : celle-ci arrête une
    instruction partie trop loin — un verrou attendu, par exemple —, là où l'autre arrête
    une transaction qui s'étire sur beaucoup d'items. `set_config` plutôt que `SET LOCAL`
    parce qu'elle se paramètre, et qu'une valeur de configuration interpolée dans du SQL
    est une faute même quand elle vient d'un entier.
    """
    await conn.execute(
        "SELECT set_config('statement_timeout', $1, true)", str(int(plan.seconds * 1000))
    )


def _timed(debut: float, plan: ApplyPlan) -> None:
    if time.monotonic() - debut > plan.seconds:
        raise ApplyTooLong(FAILURE_APPLY_TOO_LONG)


async def _duplicates(conn: Any, plan: ApplyPlan) -> list[str]:
    """Les clés que le document portait deux fois, signalées et non corrigées.

    Le dernier valide gagne — c'est ce que l'ordre d'écriture produit naturellement —, et
    le compte-rendu le SIGNALE plutôt que d'écrire le dernier en silence : la source se
    contredit, et son auteur doit l'apprendre. Cherchées en SQL sur l'aire de préparation,
    et non tenues en mémoire pendant la lecture : un index de cinquante mille clés aurait
    rendu en mémoire ce que la lecture en flux évite.
    """
    cles = await db_duplicate_keys(conn, limit=plan.detail_cap + 1)
    anomalies = [f"{ANOMALY_DUPLICATE_KEY}:{cle}" for cle in cles[: plan.detail_cap]]
    if len(cles) > plan.detail_cap:
        anomalies.append(f"{ANOMALY_DETAIL_CAPPED}:{plan.detail_cap}")
    return anomalies
