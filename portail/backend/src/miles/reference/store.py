from __future__ import annotations

from typing import Any, Protocol

from miles.reference.activation import GivenReferential
from miles.reference.model import (
    COUNTRY_ACTIVATED_EVENT,
    COUNTRY_DEACTIVATED_EVENT,
    COUNTRY_OBJECT_KIND,
    TIMEZONE_ACTIVATED_EVENT,
    TIMEZONE_DEACTIVATED_EVENT,
    TIMEZONE_OBJECT_KIND,
)

# Les requêtes du référentiel des pays. La table est DONNÉE : il n'y a ni insertion, ni
# suppression, ni renommage ici — seulement lire et basculer l'état actif. Un référentiel
# donné qu'on pourrait amender n'en serait plus un, et la migration suivante écraserait
# l'amendement.


class CountriesDb(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


async def db_list_countries(db: CountriesDb, only_active: bool) -> list[Any]:
    """Les pays, tous ou seulement les actifs. Relu à chaque appel, jamais mis en cache :
    un pays activé sert aussitôt, sans redémarrage."""
    return await db.fetch(
        "SELECT slug, alpha2, active FROM reference_countries"
        " WHERE ($1::boolean IS FALSE OR active) ORDER BY slug",
        only_active,
    )


# Le descripteur du référentiel des pays, lu par le geste partagé d'activation. Les deux
# requêtes sont écrites EN ENTIER ici : un nom de table ne se paramètre pas en SQL, et
# l'assembler par f-string rendrait indiscernable d'une injection ce qui n'en est pas une.
COUNTRIES = GivenReferential(
    object_kind=COUNTRY_OBJECT_KIND,
    activated_event=COUNTRY_ACTIVATED_EVENT,
    deactivated_event=COUNTRY_DEACTIVATED_EVENT,
    # Verrouillées AVANT l'écriture : deux bascules simultanées sur le même pays liraient
    # sinon le même état, et l'une des deux n'écrirait rien sans le savoir.
    lock_slugs=(
        "SELECT slug FROM reference_countries WHERE slug = ANY($1::text[]) ORDER BY slug FOR UPDATE"
    ),
    # `AND active <> $2` : un pays déjà dans l'état voulu n'est pas « changé ». Le rejeu du
    # même geste ne produit donc ni erreur ni event — sans cette clause, le journal
    # porterait des activations qui n'ont rien activé.
    update_active=(
        "UPDATE reference_countries SET active = $2"
        " WHERE slug = ANY($1::text[]) AND active <> $2 RETURNING slug"
    ),
)


async def db_list_timezones(
    db: CountriesDb, only_active: bool, country_slug: str | None
) -> list[Any]:
    """Les fuseaux, avec TOUS leurs pays dans l'ordre d'IANA.

    Le filtre par pays est un `EXISTS` et non une condition sur la jointure : posé sur la
    jointure, il ne laisserait remonter que le pays demandé et la ligne affichée perdrait
    les autres — `Europe/Brussels` apparaîtrait rattaché au seul Luxembourg.
    """
    return await db.fetch(
        "SELECT t.slug, t.active,"
        " coalesce(array_agg(l.country_slug ORDER BY l.rank)"
        "          FILTER (WHERE l.country_slug IS NOT NULL), '{}') AS countries"
        " FROM reference_timezones t"
        " LEFT JOIN reference_timezone_countries l ON l.timezone_slug = t.slug"
        " WHERE ($1::boolean IS FALSE OR t.active)"
        " AND ($2::text IS NULL OR EXISTS ("
        "     SELECT 1 FROM reference_timezone_countries f"
        "     WHERE f.timezone_slug = t.slug AND f.country_slug = $2))"
        " GROUP BY t.slug, t.active ORDER BY t.slug",
        only_active,
        country_slug,
    )


# Le descripteur du référentiel des fuseaux, jumeau de celui des pays. Les requêtes sont
# écrites en entier pour la même raison : un nom de table ne se paramètre pas en SQL.
TIMEZONES = GivenReferential(
    object_kind=TIMEZONE_OBJECT_KIND,
    activated_event=TIMEZONE_ACTIVATED_EVENT,
    deactivated_event=TIMEZONE_DEACTIVATED_EVENT,
    lock_slugs=(
        "SELECT slug FROM reference_timezones WHERE slug = ANY($1::text[]) ORDER BY slug FOR UPDATE"
    ),
    update_active=(
        "UPDATE reference_timezones SET active = $2"
        " WHERE slug = ANY($1::text[]) AND active <> $2 RETURNING slug"
    ),
)
