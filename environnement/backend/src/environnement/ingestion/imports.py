"""Lancer l'import d'un dépôt pris en charge, sans faire attendre l'appelant.

**Une tâche du processus qui a reçu le dépôt, et non une boucle de fond.** Une boucle de
fond rouvrirait la question du multi-instance (enabler `e0919be6`, non fait), et Gael a déjà
tranché dans ce sens le 03/11/2026 pour l'entretien des journaux : le périodique vient de
l'hôte. Ici, ce qui déclenche l'import n'est pas périodique — c'est un dépôt —, et la tâche
meurt avec lui.

**Ce qui tient le multi-instance, c'est le verrou en BASE** (`fileimport.resolve_drain`), pas
le fait qu'il n'y ait qu'un processus. Deux instances peuvent lancer leur tâche en même
temps : une seule prendra le storage, l'autre rendra zéro et son import restera en file.

**Et ce qui tient l'interruption, c'est l'entretien** (critère 14) : une tâche tuée avec le
conteneur laisse un import « en cours », que l'entretien remet en file — rejouer est sûr,
l'écriture étant différentielle. Sans ce rattrapage, une tâche de processus serait une
promesse qu'un redéploiement casse.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import structlog

from environnement.ingestion.model import Acknowledgement
from environnement.ingestion.store_imports import db_storage_of

log = structlog.get_logger(__name__)

# Comment une tâche est lancée. Injecté pour que les tests déroulent l'import eux-mêmes et
# vérifient son RÉSULTAT : une tâche de fond lancée dans un test se termine après lui, et
# un test qui ne l'attend pas ne prouve rien.
Spawn = Callable[[Coroutine[Any, Any, Any]], None]


def spawn_task(coro: Coroutine[Any, Any, Any]) -> None:
    """Lance la coroutine en tâche détachée, sans attendre son terme.

    La référence est GARDÉE le temps de la tâche : sans elle, le ramasse-miettes peut
    collecter une tâche encore en vol, et l'import s'arrêterait au milieu sans trace.
    """
    tache = asyncio.create_task(coro)
    _EN_VOL.add(tache)
    tache.add_done_callback(_EN_VOL.discard)


_EN_VOL: set[asyncio.Task[Any]] = set()


@dataclass(frozen=True)
class ImportLauncher:
    """Fait avancer la file des imports, en tâche ou tout de suite.

    Le drain lui-même est au `FileImports` ; ce qui est ici est la DÉCISION de ne pas faire
    attendre le déposant, et elle est seule à être remplaçable dans un test.
    """

    drain: Callable[[str], Awaitable[int]]
    storage_of: Callable[[str], Awaitable[str | None]]
    spawn: Spawn = field(default=spawn_task)

    async def resolve_launch(self, accuse: Acknowledgement) -> None:
        """Lance l'import du dépôt qui vient d'être pris en charge.

        Le storage est relu de la LIGNE et non reçu en argument : c'est ce qui a été
        enregistré qui fait foi, et c'est lui qui sérialise les imports.
        """
        storage = await self.storage_of(accuse.id)
        if storage is None:
            # Aucun storage sur la ligne : il n'y a rien à sérialiser, donc rien à
            # lancer. Ce n'est pas un repli silencieux — un dépôt de fichier sans storage
            # ne peut pas exister, la contrainte de la table l'interdit —, c'est le refus
            # de deviner une valeur que seul un défaut de schéma rendrait absente.
            log.warning("import_sans_storage", ingestion=accuse.id)
            return
        self.spawn(self._drained(storage))

    async def _drained(self, storage: str) -> None:
        try:
            await self.drain(storage)
        except Exception:
            # Une tâche détachée qui lève perdrait son exception en silence : l'import
            # resterait « en cours » sans que rien ne dise pourquoi. L'entretien le
            # remettra en file, mais le diagnostic doit exister maintenant.
            log.exception("import_interrompu", storage=storage)


def pooled_storage_of(pool: Any) -> Callable[[str], Awaitable[str | None]]:
    """De quoi relire le storage d'une ingestion, sur une connexion du pool.

    Fabrique partagée par l'application et par le harnais d'intégration : un harnais qui
    recompose cette glu finit par brancher autre chose que la production, et c'est la
    leçon du 29/10/2026 sur les harnais trop généreux.
    """

    async def _lookup(ingestion_id: str) -> str | None:
        async with pool.acquire() as conn:
            return await db_storage_of(conn, ingestion_id)

    return _lookup
