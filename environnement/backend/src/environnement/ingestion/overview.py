"""Ce que l'écran montre du service d'ingestion : son état, et les derniers appels.

« il faut dans l'ecran voir l'état de santé du service. et voir un log des derniers
appels. » (Gael, 02/11/2026) — et, interrogé sur ce que « état de santé » désigne :
**« les deux »**, le point d'entrée répond ET les dépôts de masse avancent.

**La seconde moitié n'a encore rien à mesurer, et l'écran le DIT.** Le mode `fichier`
est refusé tant que la story qui le sert n'est pas faite : il n'existe aucune file. Un
compteur à zéro laisserait croire qu'on surveille quelque chose ; « pas encore servi »
est une information, « 0 en attente » est un mensonge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import asyncpg

from environnement.apikeys.service import ApiKeysService
from environnement.hosting.gitstore import HostedTree
from environnement.hosting.store import db_get_hosted_version
from environnement.ingestion.methods import Endpoint, file_endpoints
from environnement.ingestion.model import MODES, SERVED_MODES
from environnement.ingestion.store import (
    Call,
    CallOutcome,
    db_call_count,
    db_call_outcome,
    db_counts,
    db_key_counts,
    db_recent_calls,
)
from environnement.sources.declarations import file_declared_sources

# Fenêtre du compteur « dépôts récents ». Une journée : c'est l'unité dans laquelle une
# intégration quotidienne se lit, et celle dans laquelle le journal se partitionnera.
RECENT_WINDOW = timedelta(days=1)
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Health:
    version_number: int | None
    version_commit: str | None
    version_served_at: datetime | None
    endpoints: tuple[Endpoint, ...]
    # Déclarées et illisibles. Les taire ferait chercher une source absente alors
    # qu'elle est là, et fautive.
    unreadable_sources: tuple[str, ...]
    active_keys: int
    never_used_keys: int
    deposits_total: int
    deposits_recent: int
    last_deposit_at: datetime | None
    # Les modes de masse ne sont pas servis : rien à surveiller, et l'écran le dit.
    bulk_modes: tuple[str, ...]


@dataclass(frozen=True)
class CallPage:
    calls: tuple[Call, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class IngestionOverview:
    pool: asyncpg.Pool
    tree: HostedTree
    keys: ApiKeysService
    now: Callable[[], datetime]

    async def resolve_health(self, *, operations: Mapping[str, str]) -> Health:
        """L'état du service, lu de la version servie et de la base. Jamais mis en cache.

        `operations` dit sous quel gabarit chaque mode est monté, et vient de la couche
        qui porte les routes : c'est
        elle qui sait où elle est montée, et le recopier ici ferait deux vérités sur
        l'adresse qu'on affiche à un tiers.
        """
        hebergee = await db_get_hosted_version(self.pool)
        declarees = await file_declared_sources(self.tree.file_text, await self.tree.file_paths())
        points = await file_endpoints(self.tree, operations=operations)
        actives, neuves = await db_key_counts(self.pool)
        comptes = await db_counts(self.pool, self.now() - RECENT_WINDOW)
        return Health(
            version_number=None if hebergee is None else hebergee.ordered_number,
            version_commit=None if hebergee is None else hebergee.ordered_commit,
            version_served_at=None if hebergee is None else hebergee.served_at,
            endpoints=points,
            unreadable_sources=declarees.unreadable,
            active_keys=actives,
            never_used_keys=neuves,
            deposits_total=comptes.total,
            deposits_recent=comptes.since,
            last_deposit_at=comptes.last_at,
            bulk_modes=tuple(mode for mode in MODES if mode not in SERVED_MODES),
        )

    async def resolve_calls(self, *, source: str | None, page: int, page_size: int) -> CallPage:
        """Les derniers appels, le plus récent d'abord.

        Le compte et la page dans la MÊME transaction : un total lu à côté pourrait
        annoncer un nombre de pages que la liste ne porte pas.
        """
        taille = max(1, min(page_size, MAX_PAGE_SIZE))
        rang = max(1, page)
        async with self.pool.acquire() as conn, conn.transaction():
            appels = await db_recent_calls(
                conn, source=source, limit=taille, offset=(rang - 1) * taille
            )
            total = await db_call_count(conn, source)
        return CallPage(tuple(appels), total, rang, taille)

    async def resolve_call_outcome(self, ingestion_id: str) -> CallOutcome | None:
        """Ce qu'un dépôt est devenu : son état, ses comptes, ses MOTIFS de rejet.

        C'est ce qui manquait pour corriger un modèle (Gael, 08/11/2026) : le journal des
        appels disait « traité » sans jamais dire pourquoi vingt-cinq mille objets
        n'étaient pas entrés. Lu à la demande, sur une ligne ouverte, jamais avec la liste.
        """
        async with self.pool.acquire() as conn:
            return await db_call_outcome(conn, ingestion_id)

    async def resolve_declared_sources(self) -> tuple[str, ...]:
        """Les sources déclarées : ce sur quoi le filtre du journal peut porter."""
        return await self.keys.resolve_declared_sources()
