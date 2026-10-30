from __future__ import annotations

from typing import Any, Protocol

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


async def db_lock_countries(db: CountriesDb, slugs: list[str]) -> set[str]:
    """Verrouille les lignes visées et rend celles qui existent.

    Verrouillées AVANT l'écriture : deux bascules simultanées sur le même pays liraient
    sinon le même état et l'une des deux n'écrirait rien sans le savoir.
    """
    rows = await db.fetch(
        "SELECT slug FROM reference_countries WHERE slug = ANY($1::text[])"
        " ORDER BY slug FOR UPDATE",
        slugs,
    )
    return {row["slug"] for row in rows}


async def db_set_countries_active(db: CountriesDb, slugs: list[str], active: bool) -> list[str]:
    """Bascule l'état actif et rend les slugs RÉELLEMENT changés.

    `AND active <> $2` : un pays déjà dans l'état voulu n'est pas « changé ». Le rejeu du
    même geste ne produit donc ni erreur ni event — sans cette clause, le journal porterait
    des activations qui n'ont rien activé.
    """
    rows = await db.fetch(
        "UPDATE reference_countries SET active = $2"
        " WHERE slug = ANY($1::text[]) AND active <> $2 RETURNING slug",
        slugs,
        active,
    )
    return sorted(row["slug"] for row in rows)
