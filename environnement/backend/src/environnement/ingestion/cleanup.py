"""Le BALAYAGE qui supprime ce que les règles désignent, et la trace qu'il laisse. `45543845`.

Les règles elles-mêmes, et les instructions qu'elles produisent, sont dans
`cleanup_rules.py` : module pur, éprouvé seul.

**Le déclenchement est la fin d'un import `traite`, et rien d'autre** (Gael, 09/11/2026 :
« le déclenchement du nettoyage se traite à la fin de l'import fichier »). Aucun
ordonnanceur n'est ajouté, et la conséquence est assumée : un storage qui ne reçoit plus
d'import ne se nettoie plus. Gael l'a tranché le même jour — « on ne traite pas le sujet
d'un storage qui cesse de recevoir des imports ». Ne pas ajouter de déclencheur d'hôte ici
sans le lui demander : un nettoyage qui tourne sans que personne ne dépose rien est un
dispositif qui supprime sans que personne ne regarde.

**Le lot n'est jamais tenu en mémoire** : on balaie par fenêtres bornées, dans l'ordre de
la colonne de la règle, et chaque fenêtre est supprimée AVEC ses events dans une
transaction courte. Un export réel compte 168 775 items.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from miles_socle.events.journal import db_write_events
from miles_socle.events.model import NewEvent, ObjectRef

from environnement.ingestion.cleanup_rules import (
    CleanupRule,
    delete_statement,
    removable,
    scan_statement,
    threshold,
)
from environnement.ingestion.writeback import Processing
from environnement.storages.model import StorageTable

log = structlog.get_logger(__name__)

OBJECT_REMOVED_EVENT = "environment.storage_object_removed"
EVENT_TYPES = frozenset({OBJECT_REMOVED_EVENT})

# Combien d'items une fenêtre emporte. Cent, comme la fenêtre de fusion : la transaction
# reste courte, et les events de la fenêtre partent en trois instructions quel que soit
# leur nombre (`db_write_events`). Plus large, on rallonge une transaction qui verrouille
# des lignes de la table que l'import vient d'écrire ; plus étroite, on paie un
# aller-retour pour dix lignes.
REMOVAL_WINDOW = 100


async def db_remove_designated(
    processing: Processing,
    table: StorageTable,
    rules: list[CleanupRule],
    *,
    now: datetime,
) -> int | None:
    """Supprime ce que les règles désignent, trace chaque suppression, rend le compte.

    **Rend `None` sans rien supprimer si une règle de péremption n'est plus évaluable** :
    sa propriété a disparu du modèle ou n'est plus projetée. Fail closed, et il porte sur
    TOUT le storage — y compris les autres règles, dont on ne sait pas si elles étaient
    censées porter seules (critère 10). Une règle de suppression qu'on ne sait plus
    évaluer ne se rabat pas sur une approximation.

    `None` et zéro ne disent donc pas la même chose : l'un est un nettoyage refusé,
    l'autre un nettoyage qui n'avait rien à sortir.
    """
    if table.unresolved_expiries:
        log.warning(
            "nettoyage_refuse",
            storage=table.storage,
            proprietes=list(table.unresolved_expiries),
        )
        return None
    if not rules:
        return 0
    total = 0
    for rule in rules:
        total += await _apply(processing, table, rule, now=now)
    return total


async def _apply(
    processing: Processing, table: StorageTable, rule: CleanupRule, *, now: datetime
) -> int:
    """Balaie une règle, fenêtre par fenêtre, jusqu'à l'épuiser."""
    seuil = threshold(rule, now)
    statement = scan_statement(table, rule)
    curseur: tuple[Any, str] | None = None
    supprimes, non_datees, exemple = 0, 0, None
    while True:
        valeur, cle = curseur if curseur is not None else (None, None)
        fenetre = await processing.db.fetch(statement, seuil, valeur, cle, REMOVAL_WINDOW)
        if not fenetre:
            break
        curseur = (fenetre[-1]["valeur"], fenetre[-1]["cle"])
        gardees: list[Any] = []
        ecartees: list[Any] = []
        for row in fenetre:
            (gardees if removable(rule, row["valeur"]) else ecartees).append(row)
        if ecartees:
            non_datees += len(ecartees)
            exemple = exemple or ecartees[0]["cle"]
        if gardees:
            supprimes += await _remove_window(processing, table, rule, gardees)
        if len(fenetre) < REMOVAL_WINDOW:
            break
    if non_datees:
        # DIT, et non tu : ces items ne sont pas supprimés, et personne ne peut deviner
        # qu'une règle de péremption ne les atteint pas. C'est la donnée qu'il faut aller
        # corriger, et la route de restitution les montre un par un, marqués non
        # supprimables.
        log.warning(
            "peremption_valeur_non_datee",
            storage=table.storage,
            propriete=rule.path,
            items=non_datees,
            exemple=exemple,
        )
    if supprimes:
        log.info(
            "items_supprimes",
            storage=table.storage,
            regle=rule.kind,
            propriete=rule.path,
            jours=rule.days,
            items=supprimes,
        )
    return supprimes


async def _remove_window(
    processing: Processing, table: StorageTable, rule: CleanupRule, rows: list[Any]
) -> int:
    """Supprime une fenêtre et écrit ses events DANS LA MÊME transaction.

    La même, parce qu'un fait observable sans sa trace est interdit par le système — et
    ici plus qu'ailleurs : une suppression sans trace ne se rattrape pas, c'est l'interdit
    que Gael a posé le premier. Une transaction PAR FENÊTRE et non une pour tout le
    nettoyage : elle verrouille des lignes de la table que l'import vient d'écrire.
    """
    async with processing.db.transaction():
        sorties = await processing.db.fetch(delete_statement(table), [row["id"] for row in rows])
        if sorties:
            await db_write_events(
                processing.db,
                [_event(processing, table, rule, row) for row in sorties],
                processing.catalog,
                processing.now,
            )
    return len(sorties)


def _event(processing: Processing, table: StorageTable, rule: CleanupRule, row: Any) -> NewEvent:
    """L'event d'une suppression : l'objet ENTIER, et la règle qui l'a désigné.

    L'objet entier parce que c'est la seule façon de rattraper une suppression — la ligne
    n'existe plus, et un event qui n'en garderait que la clé ne permettrait pas de la
    reposer. C'est cohérent avec « un event par objet écrit » (02/11/2026) et avec le
    partitionnement du journal à la journée, qui la rend tenable.
    """
    return NewEvent(
        OBJECT_REMOVED_EVENT,
        (ObjectRef(table.storage, row["cle"]),),
        processing.author,
        {
            "storage": table.storage,
            "model": table.model,
            "ingestion": processing.ingestion_id,
            "rule": rule.kind,
            "property": rule.path,
            "source": rule.source,
            "days": rule.days,
            "objet": _json(row["objet"]),
        },
    )


def _json(value: object) -> dict[str, Any]:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE : une leçon du dépôt porte le jour où
    # un test l'a oublié.
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}
