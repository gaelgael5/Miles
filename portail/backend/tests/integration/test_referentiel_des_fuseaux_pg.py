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
from miles.reference.model import TIMEZONE_ACTIVATED_EVENT, TIMEZONE_DEACTIVATED_EVENT
from miles.reference.service import CountriesService
from miles.reference.timezones import TimezonesService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# L'apostrophe est TYPOGRAPHIQUE parce que c'est celle de CLDR : c'est la valeur réelle, pas
# un choix de style. Écrite en échappement pour que le linter du dépôt ne la confonde pas
# avec une apostrophe droite — et pour que personne ne la « corrige ».
HEURE_EUROPE_CENTRALE = "heure d\u2019Europe centrale"

# Le référentiel DONNÉ des fuseaux horaires (story d4fb364a). Jumeau de celui des pays :
# ce qui leur est COMMUN — activation, repli des libellés, refus d'un slug inconnu — est
# éprouvé là-bas et par les tests unitaires du module partagé. Ce qui est éprouvé ICI est ce
# qui n'appartient qu'aux fuseaux : la liste canonique, le lien N-N vers les pays, et le
# filtre par pays pour lequel ce lien existe.


@asynccontextmanager
async def _stack(dsn: str, tmp_path: Path) -> AsyncIterator[PortalStack]:
    async with open_portal_stack(dsn, tmp_path) as portal:
        catalog = EventTypeCatalog(code_event_types())
        portal.app.state.cultures = CulturesService(portal.pool, catalog, utc_now)
        portal.app.state.countries = CountriesService(
            portal.pool, portal.app.state.cultures, catalog, utc_now
        )
        portal.app.state.timezones = TimezonesService(
            portal.pool, portal.app.state.cultures, catalog, utc_now
        )
        yield portal


async def _lire(portal: PortalStack, params: dict[str, str]) -> list[dict[str, Any]]:
    reponse = await portal.client.get("/api/timezones", params=params)
    assert reponse.status_code == 200, reponse.text
    fuseaux: list[dict[str, Any]] = reponse.json()
    return fuseaux


async def test_la_liste_canonique_est_donnee_et_inactive(blank_db: str, tmp_path: Path) -> None:
    """Critères 1 et 5 : les zones canoniques d'IANA, et aucune active à l'installation."""
    async with _stack(blank_db, tmp_path) as portal:
        fuseaux = await _lire(portal, {})

        assert len(fuseaux) == 312
        assert [f["slug"] for f in fuseaux if f["active"]] == []
        assert "Europe/Paris" in [f["slug"] for f in fuseaux]


async def test_aucun_nom_obsolete_n_est_charge(blank_db: str, tmp_path: Path) -> None:
    """Critère 2, et c'est le piège mesuré de ce ticket.

    `zone_aliases` de CLDR va du nom CANONIQUE vers l'ancien (`Europe/Kyiv` → `Europe/Kiev`) :
    filtrer sur ses clés aurait retiré les bons noms. La source est donc la table IANA, et
    ce test mesure les deux moitiés — le canonique est là, l'obsolète n'y est pas.
    """
    async with _stack(blank_db, tmp_path) as portal:
        slugs = {f["slug"] for f in await _lire(portal, {})}

        assert "Europe/Kyiv" in slugs
        assert "Europe/Kiev" not in slugs
        assert "Asia/Kolkata" in slugs
        assert "Asia/Calcutta" not in slugs
        # Ni `localtime`, qui n'est pas un fuseau, ni la famille aux signes inversés.
        assert "localtime" not in slugs
        assert not [s for s in slugs if s.startswith("Etc/")]


async def test_chaque_fuseau_porte_tous_ses_pays_dans_l_ordre_d_iana(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3, et la correction que la mesure a imposée au ticket.

    `Asia/Dubai` sert cinq pays. N'en garder qu'un laisserait 93 pays sans aucun fuseau.
    L'ordre est celui d'IANA : le premier cité est celui qu'un écran nomme s'il n'en montre
    qu'un.
    """
    async with _stack(blank_db, tmp_path) as portal:
        fuseaux = {f["slug"]: f["countries"] for f in await _lire(portal, {})}

        assert fuseaux["Asia/Dubai"] == ["ARE", "OMN", "REU", "SYC", "ATF"]
        assert fuseaux["Europe/Brussels"] == ["BEL", "LUX", "NLD"]
        # Et Monaco avec la France : lu dans la table IANA (`FR,MC`), pas de mémoire. Ce
        # test a d'abord affirmé « FRA » seul, et c'est la campagne qui a corrigé l'auteur.
        assert fuseaux["Europe/Paris"] == ["FRA", "MCO"]
        # Jamais vide : la table IANA donne au moins un pays à chacune de ses zones.
        assert [slug for slug, pays in fuseaux.items() if not pays] == []


async def test_le_filtre_par_pays_sert_un_pays_qui_n_est_premier_nulle_part(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9, et c'est l'usage POUR LEQUEL le lien existe.

    Le Luxembourg n'est le premier pays d'aucune zone. Un filtre qui ne regarderait que le
    premier ne lui rendrait rien — et 92 autres pays avec lui.
    """
    async with _stack(blank_db, tmp_path) as portal:
        luxembourg = await _lire(portal, {"country": "LUX"})
        france = await _lire(portal, {"country": "FRA"})

        assert [f["slug"] for f in luxembourg] == ["Europe/Brussels"]
        # Et la ligne garde TOUS ses pays : filtrer ne rogne pas ce qu'on affiche.
        assert luxembourg[0]["countries"] == ["BEL", "LUX", "NLD"]
        assert "Europe/Paris" in [f["slug"] for f in france]


async def test_un_pays_mal_forme_ne_filtre_rien_au_lieu_de_tout_vider(
    blank_db: str, tmp_path: Path
) -> None:
    """Un slug impossible est lu comme « pas de filtre ».

    Une liste vide pour un paramètre mal formé ferait chercher la panne du côté du
    référentiel ; la liste entière, elle, se voit.
    """
    async with _stack(blank_db, tmp_path) as portal:
        fuseaux = await _lire(portal, {"country": "xx"})

        assert len(fuseaux) == 312


async def test_le_libelle_suit_la_culture_et_l_identifiant_reste_la(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7, et la raison pour laquelle le slug ne disparaît jamais de la réponse.

    CLDR rend un nom de MÉTAZONE : « heure d'Europe centrale » vaut pour Paris, Berlin et
    Madrid. Le libellé seul ne désigne donc aucun fuseau, et c'est mesuré ici.
    """
    async with _stack(blank_db, tmp_path) as portal:
        avant = await _lire(portal, {"culture": "fr-FR", "q": "Europe/Paris"})
        assert [f["label"] for f in avant] == ["Central European Time"]

        active = await portal.client.post(
            "/api/cultures/activation", json={"codes": ["fr-FR"], "active": True}
        )
        assert active.status_code == 200, active.text

        apres = await _lire(portal, {"culture": "fr-FR", "q": "Europe/Paris"})
        assert [f["label"] for f in apres] == [HEURE_EUROPE_CENTRALE]
        # Le même libellé pour trois villes : sans le slug, l'écran serait illisible.
        berlin = await _lire(portal, {"culture": "fr-FR", "q": "Europe/Berlin"})
        assert berlin[0]["label"] == apres[0]["label"]
        assert berlin[0]["slug"] == "Europe/Berlin"


async def test_l_activation_est_journalisee_et_ne_detruit_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8. Le geste vient du module partagé : ce test vérifie qu'il est bien CÂBLÉ."""
    async with _stack(blank_db, tmp_path) as portal:
        active = await portal.client.post(
            "/api/timezones/activation",
            json={"slugs": ["Europe/Paris", "Europe/Brussels"], "active": True},
        )

        assert active.status_code == 200, active.text
        assert active.json() == {"changed": ["Europe/Brussels", "Europe/Paris"]}
        assert await _event(portal, TIMEZONE_ACTIVATED_EVENT) == {"count": 2}

        desactive = await portal.client.post(
            "/api/timezones/activation", json={"slugs": ["Europe/Brussels"], "active": False}
        )

        assert desactive.json() == {"changed": ["Europe/Brussels"]}
        assert await _event(portal, TIMEZONE_DEACTIVATED_EVENT) == {"count": 1}
        assert len(await _lire(portal, {})) == 312
        assert [f["slug"] for f in await _lire(portal, {"only_active": "true"})] == ["Europe/Paris"]


async def test_un_slug_hors_referentiel_est_refuse_en_le_nommant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10. Le refus vient du module partagé, et il nomme ce qui est fautif."""
    async with _stack(blank_db, tmp_path) as portal:
        refus = await portal.client.post(
            "/api/timezones/activation",
            json={"slugs": ["Europe/Paris", "Europe/Kiev"], "active": True},
        )

        assert refus.status_code == 422, refus.text
        assert refus.json()["detail"] == {"field": "slugs", "unknown": ["Europe/Kiev"]}
        assert [f["slug"] for f in await _lire(portal, {"only_active": "true"})] == []


async def test_la_base_refuse_un_fuseau_rattache_a_un_pays_inexistant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3, tenu par la BASE et pas seulement par le script qui engendre la migration.

    Écrit en SQL ce qu'aucune route n'offre : sans ce test, retirer la clé étrangère ne
    ferait rougir personne, et les deux référentiels pourraient se contredire.
    """
    async with _stack(blank_db, tmp_path) as portal:
        with pytest.raises(Exception, match="reference_timezone_countries_country_slug_fkey"):
            await portal.pool.execute(
                "INSERT INTO reference_timezone_countries (timezone_slug, country_slug, rank)"
                " VALUES ('Europe/Paris', 'ZZZ', 1)"
            )


async def test_aucune_route_du_referentiel_n_est_atteignable_sans_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12, fail closed."""
    async with _stack(blank_db, tmp_path) as portal:
        async with portal.anonymous() as visiteur:
            lecture = await visiteur.get("/api/timezones")
            ecriture = await visiteur.post(
                "/api/timezones/activation", json={"slugs": ["UTC"], "active": True}
            )

        assert lecture.status_code == 401, lecture.text
        assert ecriture.status_code == 401, ecriture.text


async def test_les_deux_referentiels_ne_partagent_pas_leur_etat_actif(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux référentiels jumeaux, deux états : le mécanisme est partagé, pas les données.

    Sans ce test, un descripteur mal câblé — celui des pays passé au service des fuseaux —
    ferait activer des pays depuis l'écran des fuseaux, et les deux campagnes resteraient
    vertes chacune de son côté.
    """
    async with _stack(blank_db, tmp_path) as portal:
        await portal.client.post(
            "/api/timezones/activation", json={"slugs": ["Europe/Paris"], "active": True}
        )

        pays_actifs = await portal.client.get("/api/countries", params={"only_active": "true"})
        assert pays_actifs.json() == []
        assert [f["slug"] for f in await _lire(portal, {"only_active": "true"})] == ["Europe/Paris"]
        # Et l'inverse : activer un pays ne touche aucun fuseau.
        await portal.client.post(
            "/api/countries/activation", json={"slugs": ["FRA"], "active": True}
        )
        assert [f["slug"] for f in await _lire(portal, {"only_active": "true"})] == ["Europe/Paris"]


async def _event(portal: PortalStack, event_type: str) -> dict[str, Any]:
    row = await portal.pool.fetchrow(
        "SELECT properties FROM events WHERE type = $1 ORDER BY written_at DESC LIMIT 1",
        event_type,
    )
    assert row is not None, f"aucun event {event_type}"
    charge: dict[str, Any] = json.loads(row["properties"])
    return charge
