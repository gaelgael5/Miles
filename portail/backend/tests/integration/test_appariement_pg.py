from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from miles_socle.events.model import EventTypeCatalog
from miles_socle.pairing.events import PAIRING_REQUESTED_EVENT, PEER_REGISTERED_EVENT
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.keys import fingerprint
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from miles.event_types import code_event_types
from miles.pairing.service import MODULE_NAME, PairingService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# L'appariement du module de paramétrage au module d'enrôlement (ticket ba44914b).
#
# CE QUE CES TESTS N'ÉPROUVENT PAS, et c'est tout l'intérêt : le mécanisme lui-même. Il est
# au socle depuis le 29/10/2026, le module d'environnement l'emploie, et sa campagne
# l'éprouve en entier — demande, confirmation, refus, états, avis de révocation. Le
# recopier ici prouverait seulement qu'on sait recopier un test.
#
# Ce qui est éprouvé ici est ce que le PORTAIL ajoute : que le service est câblé, qu'il
# déclare la bonne espèce, que ses routes de pair échappent au portillon de session et
# qu'elles sont bien gardées par la signature. Autrement dit tout ce qui, mal fait, ferait
# échouer l'appariement dans ce produit-ci et dans lui seul.

PUBLIC_URL = "http://parametrage.test"


@asynccontextmanager
async def _stack(
    dsn: str, tmp_path: Path, double: EnrolmentDouble | None = None
) -> AsyncIterator[PortalStack]:
    """Le montage minimal du portail, plus le service d'appariement comme `app.py` le pose.

    Le câblage suit le style de cette suite — chaque test branche ce dont il a besoin —
    et c'est lui que la garde de `test_cablage.py` lit : un service posé par l'application
    et absent de tout montage ferait échouer un test sur une erreur qui ne parle pas de lui.

    `double` remplace le réseau par une contrepartie EN PROCESSUS : le vrai module
    d'enrôlement est un autre produit, que le test de frontière interdit d'importer — et
    c'est bien ce qu'on veut. La doublure vient du socle, qui définit le protocole qu'elle
    double, et elle appelle son vérificateur plutôt que de réimplémenter la signature.
    """
    async with open_portal_stack(dsn, tmp_path) as portal:
        # LE catalogue du produit, et non une union assemblée ici. Mesuré le 29/10/2026 :
        # assemblé à la main, il contenait les types de l'identité du module que
        # `code_event_types()` avait OUBLIÉS — la suite était verte et la stack déployée
        # rendait 500 au premier `GET /api/identity`. Une doublure plus généreuse que la
        # production rend le test complaisant exactement là où il devait mordre.
        catalog = EventTypeCatalog(code_event_types())
        cipher = SecretCipher(os.urandom(32))
        portal.app.state.secrets = SecretsService(portal.pool, cipher, catalog, utc_now)
        transport = (
            httpx.ASGITransport(app=double.app())
            if double is not None
            else httpx.ASGITransport(app=FastAPI())
        )
        async with httpx.AsyncClient(transport=transport) as http:
            portal.app.state.identity = PairingService(
                portal.pool,
                portal.app.state.secrets,
                cipher,
                catalog,
                utc_now,
                http,
                PUBLIC_URL,
            )
            yield portal


async def test_le_portail_se_declare_module_de_parametrage_en_frappant(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : l'appariement aboutit, et le portail déclare SON espèce.

    L'espèce est ce que l'enrôlement affichera à l'humain qui accepte, et c'est ce qui
    doit être juste ici : un portail qui se déclarerait environnement se verrait affecter
    des devices qu'il ne sait pas servir.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as portal:
        frappe = await portal.client.post(
            "/api/identity/pairing",
            json={"base_url": PEER_ORIGIN, "name": "Portail de configuration"},
        )
        assert frappe.status_code == 202, frappe.text

        conclu = await portal.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert conclu.status_code == 200, conclu.text
        # Lu dans le corps REÇU par la contrepartie, et non dans l'intention du code : ce
        # qui compte est ce qui est réellement parti sur le réseau.
        assert b'"species": "parametrage"' in double.bodies[0]


async def test_l_echange_de_vivacite_annonce_le_nom_de_ce_module(
    blank_db: str, tmp_path: Path
) -> None:
    """Le pong dit « parametrage », et pas le nom du produit dont le code est partagé.

    Le routeur de pair est au socle et sert les deux demandeurs : un nom en dur y ferait
    répondre « environnement » au portail, et le diagnostic d'un appariement croisé
    partirait sur les clés.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as portal:
        await portal.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "Portail"}
        )
        await portail_confirme(portal)

        pong = await portal.client.post("/api/identity/peer/ping")

        assert pong.status_code == 200, pong.text
        assert pong.json()["module"] == "enrolement"
        # Et dans l'autre sens : ce que NOUS annonçons, lu chez la contrepartie.
        assert double.received[-1] == PUBLIC_URL
        assert MODULE_NAME == "parametrage"


async def portail_confirme(portal: PortalStack) -> None:
    conclu = await portal.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def test_l_identite_du_module_est_engendree_et_sa_cle_privee_reste_un_secret(
    blank_db: str, tmp_path: Path
) -> None:
    """La paire de clés naît au PREMIER USAGE, et la privée ne sort jamais.

    Le premier usage et non le démarrage : `dev-deploy.sh` lance la stack avant de jouer
    les migrations, donc sur une base neuve aucune table de ce schéma n'existe au
    démarrage — un composant qui l'exigerait tomberait en boucle de redémarrage.
    """
    async with _stack(blank_db, tmp_path) as portal:
        reponse = await portal.client.get("/api/identity")

        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["public_key_fingerprint"] == fingerprint(corps["public_key"])
        assert "private" not in reponse.text
        # La privée est rangée CHIFFRÉE dans la table des secrets, et la ligne d'identité
        # ne porte qu'un renvoi vers elle.
        assert await portal.pool.fetchval(
            "SELECT private_key_secret_slug FROM module_identity WHERE id = 'self'"
        )


async def test_les_routes_d_appariement_exigent_une_session(blank_db: str, tmp_path: Path) -> None:
    """Fail closed : ce sont des routes d'administration, pas des routes de pair.

    Elles font partir des appels signés vers un tiers et écrivent l'appariement : les
    laisser ouvertes reviendrait à laisser n'importe qui apparier ce portail.
    """
    async with _stack(blank_db, tmp_path) as portal, portal.anonymous() as visiteur:
        for chemin in ("/api/identity", "/api/identity/peer", "/api/identity/pairing/state"):
            refus = await visiteur.get(chemin)

            assert refus.status_code == 401, chemin
            assert refus.json()["detail"] == "session_requise"


async def test_les_routes_de_pair_echappent_a_la_session_mais_pas_a_la_signature(
    blank_db: str, tmp_path: Path
) -> None:
    """Les deux moitiés de la même règle, et il faut les deux.

    Le portillon ouvre ces chemins parce qu'ils sont authentifiés AUTREMENT. Vérifier
    seulement qu'ils passent prouverait qu'on a ouvert une porte ; vérifier seulement
    qu'ils refusent un appel nu ne dirait pas que le portillon les laisse arriver.
    """
    async with _stack(blank_db, tmp_path) as portal, portal.anonymous() as visiteur:
        for chemin in sorted(portal.app.state.signed_api_paths):
            refus = await visiteur.post(chemin)

            # Arrivé jusqu'à la route — donc pas « session_requise » — et refusé par elle.
            assert refus.status_code == 401, chemin
            assert refus.json()["detail"] == "signature_refusee", chemin


async def test_les_events_de_l_appariement_sont_connus_du_catalogue(
    blank_db: str, tmp_path: Path
) -> None:
    """Un type d'event absent du catalogue est REFUSÉ à l'écriture, et la cause est loin.

    Le portail a son propre catalogue : y oublier les types du socle ferait échouer
    l'appariement au moment d'écrire son event, après que l'appel réseau a réussi — et le
    diagnostic partirait sur le pair.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as portal:
        await portal.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "Portail"}
        )
        await portail_confirme(portal)

        ecrits = await portal.pool.fetch(
            "SELECT type FROM events WHERE type = ANY($1::text[])",
            [PAIRING_REQUESTED_EVENT, PEER_REGISTERED_EVENT],
        )

        assert {r["type"] for r in ecrits} == {PAIRING_REQUESTED_EVENT, PEER_REGISTERED_EVENT}
