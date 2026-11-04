from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from miles_socle.cultures.service import CulturesService
from miles_socle.events.model import EventTypeCatalog

from miles.event_types import code_event_types
from miles.reference.model import COUNTRY_ACTIVATED_EVENT, COUNTRY_DEACTIVATED_EVENT
from miles.reference.service import CountriesService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# Le référentiel DONNÉ des pays (story ccd8703c) : la liste est en base, l'administrateur
# n'y fait qu'activer et désactiver, et les libellés sont dérivés de CLDR à la lecture.
#
# Les douze critères de la story sont éprouvés ici, à l'exception de la règle de repli des
# libellés, dont les trois branches sont dans `tests/test_reference_labels.py` : c'est une
# fonction pure, et l'éprouver sans base la rend lisible. Ce qui est vérifié ici est qu'elle
# est bien CÂBLÉE — un libellé juste dans un test unitaire et absent de la route ne sert à
# personne.


@asynccontextmanager
async def _stack(dsn: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    """Le portail, ses cultures et son référentiel des pays — comme `app.py` les pose.

    Le catalogue est celui DU PRODUIT : un harnais plus généreux que la production est
    complaisant là où il devait mordre (leçon du 29/10/2026).
    """
    async with open_portal_stack(dsn, tmp_path) as portal:
        catalog = EventTypeCatalog(code_event_types())
        portal.app.state.cultures = CulturesService(portal.pool, catalog, utc_now)
        portal.app.state.countries = CountriesService(
            portal.pool, portal.app.state.cultures, catalog, utc_now
        )
        yield portal


async def _active_culture(portal: PortalStack, code: str) -> None:
    reponse = await portal.client.post(
        "/api/cultures/activation", json={"codes": [code], "active": True}
    )
    assert reponse.status_code == 200, reponse.text


async def test_la_liste_est_donnee_complete_et_inactive(blank_db: str, tmp_path: Path) -> None:
    """Critères 1, 2 et 3 : 249 pays, slug en alpha-3, et aucun actif à l'installation."""
    async with _stack(blank_db, tmp_path) as portal:
        liste = await portal.client.get("/api/countries")

        assert liste.status_code == 200, liste.text
        pays = liste.json()
        assert len(pays) == 249
        assert all(len(p["slug"]) == 3 and p["slug"].isupper() for p in pays)
        assert all(len(p["alpha2"]) == 2 for p in pays)
        # L'état neuf est « aucun pays retenu », pas « tous ». Une liste entière proposée
        # par défaut rendrait l'activation inutile.
        assert [p["slug"] for p in pays if p["active"]] == []
        france = next(p for p in pays if p["slug"] == "FRA")
        assert france["alpha2"] == "FR"


async def test_aucune_route_ne_cree_ni_ne_supprime_un_pays(blank_db: str, tmp_path: Path) -> None:
    """Critère 1, l'autre moitié : un référentiel donné n'a ni création ni suppression.

    Mesuré sur les chemins RÉELLEMENT servis, pas sur l'intention : c'est la seule façon
    de voir qu'une route d'écriture a été ajoutée par mégarde.
    """
    async with _stack(blank_db, tmp_path) as portal:
        schema = portal.app.openapi()["paths"]

        routes = {
            chemin: sorted(methodes)
            for chemin, methodes in schema.items()
            if chemin.startswith("/api/countries")
        }
        assert routes == {"/api/countries": ["get"], "/api/countries/activation": ["post"]}


async def test_le_libelle_suit_la_culture_active_du_visiteur(blank_db: str, tmp_path: Path) -> None:
    """Critères 5 et 6 : le libellé vient de CLDR, et activer une culture suffit.

    Jeu d'essai DISCRIMINANT : « Allemagne » diffère de « Germany ». Avec la France, dont
    le nom est le même dans les deux langues, le test resterait vert sans rien prouver.
    """
    async with _stack(blank_db, tmp_path) as portal:
        avant = await _lire(portal, {"culture": "fr-FR", "q": "DEU"})
        # fr-FR n'est pas encore active : c'est le repli en-US qui sert.
        assert [p["label"] for p in avant] == ["Germany"]

        await _active_culture(portal, "fr-FR")

        apres = await _lire(portal, {"culture": "fr-FR", "q": "DEU"})
        # Aucune migration, aucune saisie : activer la culture a suffi.
        assert [p["label"] for p in apres] == ["Allemagne"]


async def test_le_filtre_porte_sur_le_libelle_autant_que_sur_le_code(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9 : filtrer sur le seul code obligerait à connaître « DEU ».

    Et le filtre ignore la casse et les accents, sinon « cote » ne trouverait pas la Côte
    d'Ivoire — ce qui est le cas normal d'un administrateur qui tape vite.
    """
    async with _stack(blank_db, tmp_path) as portal:
        await _active_culture(portal, "fr-FR")

        par_libelle = await _lire(portal, {"culture": "fr-FR", "q": "allemagne"})
        assert [p["slug"] for p in par_libelle] == ["DEU"]

        sans_accent = await _lire(portal, {"culture": "fr-FR", "q": "cote d"})
        assert [p["slug"] for p in sans_accent] == ["CIV"]

        par_alpha2 = await _lire(portal, {"culture": "fr-FR", "q": "de"})
        assert "DEU" in [p["slug"] for p in par_alpha2]


async def test_l_activation_est_journalisee_et_la_desactivation_ne_detruit_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critères 7 et 8 : l'activation est un event, et désactiver ne retire pas la ligne."""
    async with _stack(blank_db, tmp_path) as portal:
        active = await portal.client.post(
            "/api/countries/activation", json={"slugs": ["FRA", "DEU"], "active": True}
        )

        assert active.status_code == 200, active.text
        assert active.json() == {"changed": ["DEU", "FRA"]}
        assert await _event(portal, COUNTRY_ACTIVATED_EVENT) == {"count": 2}
        actifs = await _lire(portal, {"only_active": "true"})
        assert [p["slug"] for p in actifs] == ["DEU", "FRA"]

        desactive = await portal.client.post(
            "/api/countries/activation", json={"slugs": ["DEU"], "active": False}
        )

        assert desactive.json() == {"changed": ["DEU"]}
        assert await _event(portal, COUNTRY_DEACTIVATED_EVENT) == {"count": 1}
        # La ligne est TOUJOURS là, et la réactiver la retrouve telle quelle.
        toujours_la = await _lire(portal, {"q": "DEU"})
        assert [(p["slug"], p["active"]) for p in toujours_la] == [("DEU", False)]
        assert len(await _lire(portal, {})) == 249


async def test_rejouer_la_meme_activation_ne_change_rien_et_n_ecrit_aucun_event(
    blank_db: str, tmp_path: Path
) -> None:
    """Un pays déjà dans l'état voulu n'est pas « changé ».

    Sans cette clause, le journal porterait des activations qui n'ont rien activé — et
    c'est ce journal qu'on relira pour savoir quand un pays a été retenu.
    """
    async with _stack(blank_db, tmp_path) as portal:
        await portal.client.post(
            "/api/countries/activation", json={"slugs": ["FRA"], "active": True}
        )
        avant = await _compte_events(portal)

        rejeu = await portal.client.post(
            "/api/countries/activation", json={"slugs": ["FRA"], "active": True}
        )

        assert rejeu.status_code == 200, rejeu.text
        assert rejeu.json() == {"changed": []}
        assert await _compte_events(portal) == avant


async def test_un_slug_hors_referentiel_est_refuse_en_le_nommant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10 : jamais créé au passage, et le refus dit LEQUEL.

    Le geste entier est refusé, pas sa moitié valide : l'écran envoie une sélection, et
    la moitié appliquée serait un état que personne n'a demandé.
    """
    async with _stack(blank_db, tmp_path) as portal:
        refus = await portal.client.post(
            "/api/countries/activation", json={"slugs": ["FRA", "XYZ"], "active": True}
        )

        assert refus.status_code == 422, refus.text
        assert refus.json()["detail"] == {"field": "slugs", "unknown": ["XYZ"]}
        assert [p["slug"] for p in await _lire(portal, {"only_active": "true"})] == []


async def test_une_selection_vide_est_refusee(blank_db: str, tmp_path: Path) -> None:
    """Un geste qui ne porte sur rien n'est pas un geste."""
    async with _stack(blank_db, tmp_path) as portal:
        refus = await portal.client.post(
            "/api/countries/activation", json={"slugs": [], "active": True}
        )

        assert refus.status_code == 422, refus.text
        assert refus.json()["detail"] == {"field": "slugs"}


async def test_une_culture_mal_formee_donne_le_repli_au_lieu_d_une_liste_vide(
    blank_db: str, tmp_path: Path
) -> None:
    """La culture vient d'un paramètre d'URL : validée avant d'aller lire CLDR avec elle.

    Lue comme « pas de culture » plutôt que refusée — un écran qui afficherait une liste
    vide pour un paramètre mal formé ferait chercher la panne du côté du référentiel.
    """
    async with _stack(blank_db, tmp_path) as portal:
        pays = await _lire(portal, {"culture": "../../etc/passwd", "q": "FRA"})

        assert [p["label"] for p in pays] == ["France"]


async def test_la_base_refuse_un_slug_qui_n_est_pas_de_l_alpha_3(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, tenu par la BASE et pas seulement par le code.

    Écrit en SQL ce qu'aucune route n'offre : sans ce test, retirer le CHECK ne ferait
    rougir personne, puisque le service n'insère jamais.
    """
    async with _stack(blank_db, tmp_path) as portal:
        with pytest.raises(Exception, match="reference_countries_slug_check"):
            await portal.pool.execute(
                "INSERT INTO reference_countries (slug, alpha2) VALUES ('fr', 'FR')"
            )


async def test_aucune_route_du_referentiel_n_est_atteignable_sans_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12, fail closed. Le portillon refuse, et il faut le mesurer."""
    async with _stack(blank_db, tmp_path) as portal:
        async with portal.anonymous() as visiteur:
            lecture = await visiteur.get("/api/countries")
            ecriture = await visiteur.post(
                "/api/countries/activation", json={"slugs": ["FRA"], "active": True}
            )

        assert lecture.status_code == 401, lecture.text
        assert ecriture.status_code == 401, ecriture.text


async def _lire(portal: PortalStack, params: dict[str, str]) -> list[dict[str, Any]]:
    reponse = await portal.client.get("/api/countries", params=params)
    assert reponse.status_code == 200, reponse.text
    pays: list[dict[str, Any]] = reponse.json()
    return pays


async def _event(portal: PortalStack, event_type: str) -> dict[str, Any]:
    row = await portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = $1 ORDER BY written_at DESC LIMIT 1",
        event_type,
    )
    assert row is not None, f"aucun event {event_type}"
    charge: dict[str, Any] = json.loads(row["properties"])
    return charge


async def _compte_events(portal: PortalStack) -> int:
    compte = await portal.pool.fetchval("SELECT count(*) FROM events WHERE type LIKE 'country.%'")
    return int(compte)
