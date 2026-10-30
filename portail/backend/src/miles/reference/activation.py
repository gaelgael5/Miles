from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

log = structlog.get_logger(__name__)

# Le geste commun aux référentiels DONNÉS : activer et désactiver une sélection.
#
# EXTRAIT AU SECOND USAGE, pas avant. Les pays l'ont porté seuls le 30/10/2026 ; les
# fuseaux horaires en avaient besoin le même jour, et la règle du dépôt est d'extraire à ce
# moment-là. Ce qui est partagé est la partie à invariants : verrou avant écriture, tout ou
# rien, et « déjà dans l'état voulu n'est pas un changement ». Dupliquée, c'est à deux
# endroits qu'elle dériverait.
#
# Ce qui N'EST PAS partagé : la LECTURE. Un pays porte son alpha-2 et dérive son libellé de
# lui ; un fuseau porte ses pays et dérive son libellé de son identifiant. Les fondre
# demanderait un descripteur de colonnes, c'est-à-dire du SQL composé à l'exécution.

# Borne du nombre de slugs qu'un seul geste peut changer. Généreuse — on peut tout
# sélectionner — mais bornée : la charge vient d'un appel HTTP.
MAX_SLUGS_PER_CHANGE = 500


class ReferentialError(Exception):
    """Refus ; rien n'a été écrit."""


class UnknownSlugsError(ReferentialError):
    """Des slugs hors référentiel. Nommés, parce qu'ils viennent d'une saisie d'écran."""

    def __init__(self, slugs: tuple[str, ...]) -> None:
        super().__init__(f"{len(slugs)} entrée(s) inconnue(s)")
        self.slugs = slugs


class EmptyChangeError(ReferentialError):
    """Aucune entrée désignée, ou trop. Un geste qui ne porte sur rien n'est pas un geste."""


@dataclass(frozen=True)
class GivenReferential:
    """Ce qui distingue un référentiel donné d'un autre : son journal et ses requêtes.

    Les requêtes sont des littéraux ÉCRITS EN ENTIER, un jeu par référentiel, et jamais
    composés : un nom de table ne se paramètre pas en SQL, et l'assembler par f-string
    rendrait indiscernable d'une injection ce qui n'en est pas une. Trois chaînes recopiées
    coûtent moins que cette ambiguïté.
    """

    object_kind: str
    activated_event: str
    deactivated_event: str
    # Verrouille les lignes visées et rend celles qui existent : $1 = les slugs.
    lock_slugs: str
    # Bascule l'état et rend les slugs RÉELLEMENT changés : $1 = les slugs, $2 = l'état.
    update_active: str


async def resolve_set_active(
    *,
    pool: asyncpg.Pool,
    catalog: EventTypeCatalog,
    now: Callable[[], datetime],
    referential: GivenReferential,
    author: EventAuthor,
    slugs: Sequence[str],
    active: bool,
) -> list[str]:
    """Applique exactement la sélection reçue ; rend les slugs réellement changés.

    Dans UNE transaction, verrou d'abord. L'écran envoie une sélection entière, et la
    moitié appliquée serait un état que personne n'a demandé.
    """
    voulus = sorted(set(slugs))
    if not voulus or len(voulus) > MAX_SLUGS_PER_CHANGE:
        raise EmptyChangeError
    async with pool.acquire() as conn, conn.transaction():
        connus = {row["slug"] for row in await conn.fetch(referential.lock_slugs, voulus)}
        inconnus = tuple(slug for slug in voulus if slug not in connus)
        if inconnus:
            # Nommés, et refusés AVANT toute écriture : un slug hors référentiel vient
            # d'une saisie, et le créer au passage ferait du référentiel donné une liste
            # ouverte.
            raise UnknownSlugsError(inconnus)
        rows = await conn.fetch(referential.update_active, voulus, active)
        changes = sorted(row["slug"] for row in rows)
        if changes:
            event = NewEvent(
                referential.activated_event if active else referential.deactivated_event,
                tuple(ObjectRef(referential.object_kind, slug) for slug in changes),
                author,
                {"count": len(changes)},
            )
            await db_write_event(conn, event, catalog, now)
    log.info("referentiel_change", kind=referential.object_kind, active=active, count=len(changes))
    return changes


def foldcase(text: str) -> str:
    """Repli de casse et d'accents, pour que le filtre trouve « cote » dans « Côte ».

    Partagé par les deux référentiels : le filtre d'un écran d'activation se comporte
    pareil partout, et un administrateur qui tape vite ne doit pas avoir à savoir lequel
    pardonne les accents.
    """
    decompose = unicodedata.normalize("NFD", text)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn").casefold()


def matches(aiguille: str, *champs: Any) -> bool:
    """Le filtre d'un référentiel : vrai si l'aiguille est dans l'un des champs donnés."""
    return any(aiguille in foldcase(str(champ)) for champ in champs if champ is not None)
