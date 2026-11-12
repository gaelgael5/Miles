from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from miles_socle.cultures.service import CulturesService

from miles.event_types import code_event_catalog
from miles.reference.holidays import bundled_dates
from miles.reference.service import CountriesService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# L'association pays → fichier de règles de jours fériés (Gael, 11/11/2026), chargée par la
# migration 0033 depuis le TOC de calendarium.
#
# Ces tests tournent contre la VRAIE base et le VRAI moteur, pas des doublures : c'est le
# seul endroit où l'on vérifie que la migration engendrée et le paquet installé parlent du
# même référentiel. Un nom de pays juste dans la base mais absent du moteur ne se voit
# nulle part ailleurs — et c'est exactement ce que `regles_indisponibles` nomme.
#
# Le découpage de la fenêtre et la dérivation du lien sont éprouvés sans base dans
# `tests/test_reference_holidays.py` : ce sont des fonctions pures. Ce qui est vérifié ici,
# c'est qu'elles sont CÂBLÉES.

RAW = "https://raw.githubusercontent.com/gaelgael5/calendarium/main"
PAGE = "https://github.com/gaelgael5/calendarium/blob/main"
CHEMIN = "/src/calendarium/data/countries"


@asynccontextmanager
async def _stack(dsn: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    async with open_portal_stack(dsn, tmp_path) as portal:
        catalog = code_event_catalog()
        portal.app.state.cultures = CulturesService(portal.pool, catalog, utc_now)
        portal.app.state.countries = CountriesService(
            portal.pool, portal.app.state.cultures, catalog, utc_now, bundled_dates()
        )
        yield portal


async def test_la_migration_associe_les_111_pays_verifies(blank_db: str, tmp_path: Path) -> None:
    """Les 111 pays du TOC sont en base, et leur slug est un pays du référentiel.

    Le compte est la preuve que la clé étrangère n'a refusé aucune ligne : un alpha-3 mal
    rapproché aurait fait échouer la migration, donc le démarrage.
    """
    async with _stack(blank_db, tmp_path) as portal:
        async with portal.pool.acquire() as conn:
            total = await conn.fetchval("SELECT count(*) FROM reference_country_holidays")
            orphelins = await conn.fetchval(
                "SELECT count(*) FROM reference_country_holidays h"
                " LEFT JOIN reference_countries c ON c.slug = h.slug"
                " WHERE c.slug IS NULL"
            )

        assert total == 111
        assert orphelins == 0


async def test_la_liste_des_pays_DIT_lesquels_ont_des_regles(blank_db: str, tmp_path: Path) -> None:
    """L'association se voit depuis la liste, sans déplier 249 pays un par un (critère)."""
    async with _stack(blank_db, tmp_path) as portal:
        liste = await portal.client.get("/api/countries")

        assert liste.status_code == 200, liste.text
        pays = {p["slug"]: p for p in liste.json()}
        assert pays["FRA"]["has_holidays"] is True
        # L'Antarctique est dans l'ISO 3166-1 et n'a aucun jour férié déclaré : c'est
        # l'état NORMAL de 138 des 249 pays, pas une anomalie.
        assert pays["ATA"]["has_holidays"] is False
        assert sum(1 for p in pays.values() if p["has_holidays"]) == 111


async def test_la_france_rend_son_fichier_source_et_la_page_a_cliquer(
    blank_db: str, tmp_path: Path
) -> None:
    """Les deux URL, et c'est ce que l'écran montre : la source et le lien (critère)."""
    async with _stack(blank_db, tmp_path) as portal:
        reponse = await portal.client.get("/api/countries/FRA/holidays")

        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        # Le nom de calendarium, qui est la clé du moteur et non le libellé affiché.
        assert corps["country"] == "France"
        assert corps["source_url"] == f"{RAW}{CHEMIN}/date_France.json"
        assert corps["page_url"] == f"{PAGE}{CHEMIN}/date_France.json"


async def test_les_jours_calcules_couvrent_les_douze_prochains_mois(
    blank_db: str, tmp_path: Path
) -> None:
    """La fenêtre annoncée, et des jours dedans — calculés, jamais stockés (critère)."""
    async with _stack(blank_db, tmp_path) as portal:
        reponse = await portal.client.get("/api/countries/FRA/holidays")

        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        debut = dt.date.fromisoformat(corps["start"])
        fin = dt.date.fromisoformat(corps["end"])
        assert (fin.year - debut.year, fin.month, fin.day) == (1, debut.month, debut.day)
        jours = corps["days"]
        # La fête nationale tombe forcément dans une fenêtre de douze mois, quelle que
        # soit la date du jour : c'est une assertion qui ne dépend pas de l'horloge.
        noms = {j["name"] for j in jours}
        assert "Bastille Day" in noms
        assert "Christmas Day" in noms
        # Chaque jour rendu est DANS la fenêtre, par sa date légale ou par son report.
        for jour in jours:
            legale = dt.date.fromisoformat(jour["date"])
            chome = dt.date.fromisoformat(jour["observed"])
            assert debut <= legale <= fin or debut <= chome <= fin
        # Ordonnés sur la date légale : l'écran les affiche dans cet ordre sans retrier.
        assert [j["date"] for j in jours] == sorted(j["date"] for j in jours)


async def test_un_pays_sans_regles_est_un_refus_NOMME_et_non_une_panne(
    blank_db: str, tmp_path: Path
) -> None:
    """Calendarium couvre 111 pays ; les 138 autres ne sont pas des erreurs (critère)."""
    async with _stack(blank_db, tmp_path) as portal:
        reponse = await portal.client.get("/api/countries/ATA/holidays")

        assert reponse.status_code == 404
        assert reponse.json()["reason"] == "aucune_regle"


async def test_un_slug_mal_forme_rend_le_meme_refus_qu_un_pays_sans_regles(
    blank_db: str, tmp_path: Path
) -> None:
    """Il ne désigne aucun pays, et les distinguer renseignerait sur le contenu de la base."""
    async with _stack(blank_db, tmp_path) as portal:
        for slug in ("fr", "FRANCE", "F%27R"):
            reponse = await portal.client.get(f"/api/countries/{slug}/holidays")

            assert reponse.status_code == 404, slug
            assert reponse.json()["reason"] == "aucune_regle", slug


async def test_aucune_route_ne_cree_ni_ne_change_une_association(
    blank_db: str, tmp_path: Path
) -> None:
    """L'association est DONNÉE : aucune route ne l'écrit, comme pour les pays eux-mêmes."""
    async with _stack(blank_db, tmp_path) as portal:
        for methode in ("POST", "PUT", "PATCH", "DELETE"):
            # `request` et non `client.delete(...)` : httpx refuse un corps sur `delete`,
            # et c'est bien un corps qu'on veut présenter — une route qui écrirait
            # écrirait CECI.
            reponse = await portal.client.request(
                methode, "/api/countries/FRA/holidays", json={"country": "Atlantis"}
            )

            assert reponse.status_code == 405, f"{methode} : {reponse.text}"
        async with portal.pool.acquire() as conn:
            nom = await conn.fetchval(
                "SELECT calendarium_country FROM reference_country_holidays WHERE slug = $1",
                "FRA",
            )
        assert nom == "France"


async def test_tous_les_pays_associes_sont_CONNUS_du_moteur_installe(
    blank_db: str, tmp_path: Path
) -> None:
    """La garde que rien d'autre ne tient : la base et le paquet parlent du même référentiel.

    C'est la confrontation des DEUX déclarations — la migration engendrée depuis le TOC
    d'une version, et les fichiers embarqués par la version installée. Elles peuvent
    divulguer : une montée de calendarium qui retirerait un pays du palier vérifié rendrait
    `regles_indisponibles` sur son écran, et ce test le dirait avant la livraison.
    """
    async with _stack(blank_db, tmp_path) as portal:
        async with portal.pool.acquire() as conn:
            rows = await conn.fetch("SELECT slug FROM reference_country_holidays ORDER BY slug")

        refuses = []
        for row in rows:
            reponse = await portal.client.get(f"/api/countries/{row['slug']}/holidays")
            if reponse.status_code != 200:
                refuses.append((row["slug"], reponse.status_code, reponse.text[:80]))

        assert refuses == []
