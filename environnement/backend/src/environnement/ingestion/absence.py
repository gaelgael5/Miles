"""La MARQUE D'ABSENCE : ce qu'un import complet par fichier n'a pas porté. Story `82bc9dca`.

Décision de Gael du 09/11/2026, dans ses mots : « si clef d'item pas présente, lors d'un
import full par upload de fichier, l'item est flagué en base. […] si à l'import suivant
l'item n'est pas dedans non plus on ne retouche pas l'item déjà marqué missing dans le
précédent import. »

**Ce module ne supprime rien**, et ne lit aucune règle de nettoyage. Il rend visible ce qui
est absent ; la suppression est un autre ticket, et elle lira cette date-là.

**La LEVÉE de la marque n'est pas ici** : elle appartient à l'écriture des objets
(`store_merge`), seule à savoir quelles clés un dépôt a portées. Ici se fait la pose, qui
est l'inverse — ce dont le document N'A PAS parlé — et qui ne peut donc se faire qu'une
fois le document lu en entier.

**L'ensemble des clés du fichier n'est jamais tenu en mémoire** (interdit du ticket : un
export réel en compte des centaines de milliers, 168 775 mesurées sur `pudo.accounts`).
Deux choses déjà en base le remplacent : `vu_le`, qui avance à chaque passage d'un import
sur une clé même sans changement, et l'aire de préparation de cet import, qui porte une
ligne par item lu — rejeté compris. L'absence se DÉRIVE de ces deux-là.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import structlog

from environnement.ingestion.staging import PREPARED_TABLE
from environnement.ingestion.store_merge import IMPORT_ORIGIN
from environnement.storages.ddl import quoted
from environnement.storages.model import ABSENCE_COLUMN, StorageTable

log = structlog.get_logger(__name__)


class AbsenceDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


def mark_statement(table: StorageTable) -> str:
    """L'instruction qui pose la marque, et rend le nombre de lignes marquées.

    Les identités sont CITÉES, jamais concaténées : le schéma et la table viennent d'un
    paramétrage venu du réseau, et PostgreSQL n'a pas de requête paramétrée pour une
    identité. Même barrière qu'au DDL et à la fusion, au même endroit.

    Les quatre clauses du `WHERE` portent chacune une décision du ticket, et aucune n'est
    redondante :

    - `absent_depuis IS NULL` — **la date d'une marque ne bouge plus.** C'est elle qui
      donne « absent depuis N jours » ; la rafraîchir à chaque import rendrait le délai
      inatteignable et aucun item ne sortirait jamais.
    - `origine = 'import'` — **un item posé à la main n'est jamais marqué.** Aucun import
      ne le porte jamais : le marquer le sortirait au premier nettoyage, et au pire moment
      puisque personne ne surveille un objet de test.
    - `vu_le < $2` — ce que CET import n'a pas touché. `vu_le` avance pour toute clé que
      l'import a portée, même quand l'objet n'a pas changé (story `d680e811`), donc la
      frontière est l'instant où l'import a commencé. Un dépôt unitaire arrivé pendant
      l'import avance aussi `vu_le`, et son item n'est donc pas marqué : la source en a
      parlé, c'est la bonne lecture.
    - `NOT EXISTS (… aire de préparation …)` — **un item dont la clé était dans le fichier
      mais dont l'objet a été REJETÉ n'est pas marqué.** `vu_le` ne l'a pas vu avancer,
      puisque rien n'a été écrit pour lui ; sans cette clause il serait marqué absent alors
      que la source en parle fidèlement, et supprimé au bout du délai — c'est-à-dire
      exactement l'item qu'il fallait aller corriger. L'aire porte une ligne par item lu,
      rejeté compris, et c'est pourquoi elle est interrogée plutôt qu'un ensemble de clés.
    """
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    # S608 signale l'assemblage, à juste titre : il n'existe pas de requête paramétrée
    # pour un NOM. Les SEULES valeurs interpolées sont `cible` et la colonne, passées par
    # `quoted` ou littérales de ce dépôt ; l'instant et la frontière partent en paramètres.
    return f"""
        UPDATE {cible} AS c SET {quoted(ABSENCE_COLUMN)} = $1
        WHERE c.{quoted(ABSENCE_COLUMN)} IS NULL
          AND c.origine = '{IMPORT_ORIGIN}'
          AND c.vu_le < $2
          AND NOT EXISTS (
              SELECT 1 FROM pg_temp.{PREPARED_TABLE} p WHERE p.cle = c.cle
          )
    """  # noqa: S608


_UNKEYED = f"SELECT count(*) FROM pg_temp.{PREPARED_TABLE} WHERE cle IS NULL"  # noqa: S608


async def db_mark_absent(db: AbsenceDb, table: StorageTable, *, started_at: datetime) -> int | None:
    """Marque ce que cet import n'a pas porté. Rend le nombre de marques posées.

    **Rend `None` sans rien marquer si l'import a lu un item dont la CLÉ n'a pas pu être
    extraite.** Un tel item n'est protégé par rien : l'aire le porte, mais sans clé, donc
    la ligne qu'il désignait — s'il en désignait une — serait marquée absente alors que le
    document en parlait. On préfère ne rien marquer et le dire : une marque de trop devient
    une suppression N jours plus tard, tandis qu'une marque en retard se rattrape au
    prochain import complet. C'est un repli VOLONTAIRE, et il est journalisé pour qu'un
    storage qui ne se nettoie jamais puisse s'expliquer.

    La date posée est l'instant de DÉBUT de l'import, le même qui sert de frontière. Deux
    instants différents — la frontière et la marque — auraient fait répondre « absent
    depuis » et « vu avant » à deux questions qu'on croit identiques.
    """
    sans_cle = int(await db.fetchval(_UNKEYED) or 0)
    if sans_cle:
        log.warning(
            "marquage_absence_abandonne",
            storage=table.storage,
            items_sans_cle=sans_cle,
        )
        return None
    rendu = await db.execute(mark_statement(table), started_at, started_at)
    marques = _affected(rendu)
    if marques:
        log.info("absences_marquees", storage=table.storage, items=marques)
    return marques


def _affected(tag: str) -> int:
    """Le nombre de lignes d'un « UPDATE n » d'asyncpg. Mesuré, et non déduit du succès."""
    morceaux = tag.split()
    return int(morceaux[-1]) if morceaux and morceaux[-1].isdigit() else 0
