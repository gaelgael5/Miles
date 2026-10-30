from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.testing.enrolment_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

from miles.event_types import code_event_types
from miles.gitaccess.confide import GitConfidingService
from miles.gitaccess.confide_model import (
    CONFIDED_EVENT,
    CREDENTIAL_RENEWED_EVENT,
    TRANSMISSION_FAILED_EVENT,
)
from miles.gitaccess.connections import ConnectionsService
from miles.gitaccess.dependents import DependentsVerifier
from miles.gitaccess.resolver import AccessResolver
from miles.gitaccess.store_confide import db_connections_using
from miles.pairing.service import PairingService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# Le CONFIAGE des connexions git au module d'enrôlement, vu de l'émetteur (ticket edcf78bc).
#
# Cette campagne-ci éprouve ce qui PART : la composition du corps, les déclencheurs, la
# trace de ce qui a été transmis et ce que l'écran en dit. La RÉCEPTION est éprouvée par la
# campagne du module d'enrôlement, contre son vrai code. Les deux moitiés sont nécessaires :
# mesuré le 29/10/2026, une faute dans un corps émis reste invisible d'une campagne qui
# emploie une doublure composant son propre corps.

PUBLIC_URL = "http://parametrage.test"
# Valeur distinctive : on la cherchera TELLE QUELLE dans les corps partis, dans les
# réponses d'API et dans le journal. Un jeu d'essai banal rendrait ces recherches aveugles.
CREDENTIAL = "pat-du-portail-4c81de-ne-doit-jamais-sortir"
RENOUVELE = "pat-du-portail-renouvele-93fb02"


@asynccontextmanager
async def _stack(
    dsn: str, tmp_path: Path, double: EnrolmentDouble, *, apparie: bool = True
) -> AsyncIterator[tuple[PortalStack, EnrolmentDouble]]:
    """Le portail, ses connexions git, et le service qui les confie — comme `app.py` les pose.

    Les deux rappels d'`app.py` — PAT remplacé, appariement conclu — sont posés ici de la
    même façon : par des fermetures qui relisent `app.state` au moment de l'appel. Les
    recomposer autrement ferait éprouver un câblage que la production n'a pas.
    """
    async with open_portal_stack(dsn, tmp_path) as portal:
        catalog = EventTypeCatalog(code_event_types())
        cipher = SecretCipher(os.urandom(32))
        secrets = SecretsService(portal.pool, cipher, catalog, utc_now, _pat_remplace(portal))
        state = portal.app.state
        state.secrets = secrets
        hosts: tuple[str, ...] = ()
        state.git_connections = ConnectionsService(
            portal.pool,
            AccessResolver(secrets),
            DependentsVerifier(portal.pool, catalog, utc_now, hosts),
            catalog,
            utc_now,
            hosts,
        )
        transport = httpx.ASGITransport(app=double.app())
        async with httpx.AsyncClient(transport=transport) as http:
            state.identity = PairingService(
                portal.pool,
                secrets,
                cipher,
                catalog,
                utc_now,
                http,
                PUBLIC_URL,
                on_paired=_appariement_conclu(portal),
            )
            state.git_confiding = GitConfidingService(
                portal.pool, secrets, state.identity, catalog, utc_now
            )
            if apparie:
                await _apparie(portal, double)
            yield portal, double


def _pat_remplace(portal: PortalStack) -> Any:
    async def rappel(author: Any, slug: str) -> None:
        connexions = await db_connections_using(portal.pool, slug)
        if not connexions:
            return
        await portal.app.state.git_confiding.resolve_transmit_after(
            author, "credential_remplace", connexions
        )

    return rappel


def _appariement_conclu(portal: PortalStack) -> Any:
    async def rappel(author: Any) -> None:
        await portal.app.state.git_confiding.resolve_transmit_after(author, "appariement_conclu")

    return rappel


async def _apparie(portal: PortalStack, double: EnrolmentDouble) -> None:
    frappe = await portal.client.post(
        "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "Portail"}
    )
    assert frappe.status_code == 202, frappe.text
    conclu = await portal.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text


async def _secret(portal: PortalStack, slug: str, valeur: str) -> None:
    cree = await portal.client.post(
        "/api/secrets",
        json={"slug": slug, "label": f"PAT {slug}", "secret_type": "GIT_TOKEN", "value": valeur},
    )
    assert cree.status_code == 201, cree.text


async def _connexion(portal: PortalStack, identifiant: str, slug: str) -> Any:
    return await portal.client.post(
        "/api/git-connections",
        json={
            "id": identifiant,
            "label": f"Connexion {identifiant}",
            "base_url": "https://github.com/yoops",
            "token_secret_slug": slug,
        },
    )


async def test_une_connexion_declaree_part_aussitot_avec_son_credential(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : saisie une fois ici, disponible là-bas sans aucune ressaisie.

    Lu dans le corps REÇU par la contrepartie, et non dans l'intention du code : ce qui
    compte est ce qui est réellement parti sur le réseau.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)

        declaree = await _connexion(portail, "yoops", "pat-yoops")

        assert declaree.status_code == 201, declaree.text
        charge = pair.confided[-1]
        assert charge["connections"] == [
            {
                "id": "yoops",
                "label": "Connexion yoops",
                "base_url": "https://github.com/yoops",
                "credential": CREDENTIAL,
                "workspaces": [],
            }
        ]
        etat = await portail.client.get("/api/git-connections/confided")
        assert etat.status_code == 200, etat.text
        assert etat.json()["up_to_date"] is True
        assert etat.json()["connections"] == 1
        assert etat.json()["peer_base_url"] == PEER_ORIGIN
        # Le credential voyage, mais il ne se LIT nulle part chez nous : ni dans la liste
        # des connexions, ni dans l'état du confiage (critère 2).
        liste = await portail.client.get("/api/git-connections")
        assert CREDENTIAL not in liste.text
        assert CREDENTIAL not in etat.text


async def test_le_pat_remplace_repart_aussitot_et_nomme_la_connexion_au_journal(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4, qui est la raison d'être du ticket : « renouvelable d'un seul geste ».

    Le geste est fait LÀ OÙ LE PAT A ÉTÉ SAISI — l'écran des secrets, servi par le socle —
    et personne ne touche à un environnement. Le journal nomme en plus la CONNEXION, que
    l'event du socle ne dit pas : lui ne connaît que le slug du secret (critère 11).
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        await _connexion(portail, "yoops", "pat-yoops")
        premiere = pair.confided[-1]["revision"]

        remplace = await portail.client.put(
            "/api/secrets/pat-yoops/value", json={"value": RENOUVELE}
        )

        assert remplace.status_code == 204, remplace.text
        charge = pair.confided[-1]
        assert charge["connections"][0]["credential"] == RENOUVELE
        assert int(str(charge["revision"])) > int(str(premiere))
        renouvele = await _event(portail, CREDENTIAL_RENEWED_EVENT)
        assert renouvele["peer_base_url"] == PEER_ORIGIN
        await _aucun_credential_au_journal(portail)


async def test_un_secret_sans_rapport_avec_git_ne_declenche_aucune_transmission(
    blank_db: str, tmp_path: Path
) -> None:
    """Le pendant du test ci-dessus : le filtre existe, et il mord.

    La plupart des secrets de l'instance n'ont rien à voir avec git. Transmettre à chaque
    remplacement ferait des révisions que rien ne justifie, et ferait repartir des
    credentials sans raison.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        cree = await portail.client.post(
            "/api/secrets",
            json={
                "slug": "oidc",
                "label": "Secret client OIDC",
                "secret_type": "OIDC_CLIENT_SECRET",
                "value": "sans-rapport",
            },
        )
        assert cree.status_code == 201, cree.text
        avant = len(pair.confided)

        remplace = await portail.client.put("/api/secrets/oidc/value", json={"value": "autre"})

        assert remplace.status_code == 204, remplace.text
        assert len(pair.confided) == avant


async def test_la_suppression_d_une_connexion_la_retire_de_l_etat_transmis(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9 : la suppression n'a pas de message à elle, c'est son absence qui compte."""
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        await _secret(portail, "pat-autre", RENOUVELE)
        await _connexion(portail, "yoops", "pat-yoops")
        await _connexion(portail, "autre", "pat-autre")
        assert len(pair.confided[-1]["connections"]) == 2  # type: ignore[arg-type]

        supprimee = await portail.client.delete("/api/git-connections/autre")

        assert supprimee.status_code == 204, supprimee.text
        assert [c["id"] for c in pair.confided[-1]["connections"]] == ["yoops"]  # type: ignore[union-attr]


async def test_l_appariement_conclu_confie_ce_qui_etait_deja_saisi(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 pour les connexions déclarées AVANT l'appariement.

    Sans ce rappel, elles attendraient un geste humain, et « sans aucune ressaisie » ne
    serait vrai que pour celles déclarées après.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double, apparie=False) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        declaree = await _connexion(portail, "yoops", "pat-yoops")
        assert declaree.status_code == 201, declaree.text
        # Rien n'est parti : il n'y a personne à qui confier, et ce n'est pas une panne.
        assert pair.confided == []
        etat = await portail.client.get("/api/git-connections/confided")
        assert etat.json() == {
            "peer_base_url": None,
            "revision": None,
            "transmitted_at": None,
            "up_to_date": False,
            "connections": 1,
        }

        await _apparie(portail, pair)

        assert [c["id"] for c in pair.confided[-1]["connections"]] == ["yoops"]  # type: ignore[union-attr]
        confie = await _event(portail, CONFIDED_EVENT)
        assert confie["trigger"] == "appariement_conclu"


async def test_un_module_d_enrolement_qui_refuse_ne_fait_pas_echouer_la_declaration(
    blank_db: str, tmp_path: Path
) -> None:
    """Un geste d'administration ne doit pas échouer parce qu'un autre module refuse.

    Ce qui reste d'un refus : la connexion est déclarée, le journal porte la cause, et
    l'écran dit « à retransmettre » — jamais « confiées » pour une transmission qui n'est
    pas arrivée.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        pair.confide_status = 409
        pair.confide_payload = {"detail": "espece_sans_connexions_git"}

        declaree = await _connexion(portail, "yoops", "pat-yoops")

        assert declaree.status_code == 201, declaree.text
        etat = await portail.client.get("/api/git-connections/confided")
        assert etat.json()["up_to_date"] is False
        assert etat.json()["transmitted_at"] is None
        echec = await _event(portail, TRANSMISSION_FAILED_EVENT)
        assert echec == {"trigger": "connexion_declaree", "reason": "espece_sans_connexions_git"}


async def test_le_geste_manuel_rend_le_refus_du_pair_au_lieu_de_l_avaler(
    blank_db: str, tmp_path: Path
) -> None:
    """La transmission demandée par une PERSONNE doit dire pourquoi elle ne passe pas.

    C'est la seule différence de politique avec les déclencheurs automatiques, et elle est
    volontaire : eux protègent un geste déjà commis, celle-ci répond à une question.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, pair):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        await _connexion(portail, "yoops", "pat-yoops")
        pair.confide_status = 409
        pair.confide_payload = {"detail": "revision_depassee", "held_revision": 99}

        refus = await portail.client.post("/api/git-connections/confided")

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == {"code": "refusee", "peer_detail": "revision_depassee"}


async def test_la_trace_de_confiage_appartient_au_pair_a_qui_l_on_a_transmis(
    blank_db: str, tmp_path: Path
) -> None:
    """Réapparié ailleurs, on n'a rien transmis à celui-là — et l'écran doit le dire.

    L'invariant est tenu par la JOINTURE sur l'origine du pair, pas par une clause qu'on
    peut oublier d'écrire. Même leçon que l'environnement assigné du module
    d'environnement, rangé sous son pair le 29/10/2026.
    """
    double = EnrolmentDouble()
    async with _stack(blank_db, tmp_path, double) as (portail, _):
        await _secret(portail, "pat-yoops", CREDENTIAL)
        await _connexion(portail, "yoops", "pat-yoops")
        assert (await portail.client.get("/api/git-connections/confided")).json()["up_to_date"]

        # Le pair change d'identité : c'est ce qu'un ré-appariement vers une autre
        # origine produit. Écrit en SQL parce qu'aucune route ne le fait — ce qui est
        # éprouvé ici est la LECTURE, et qu'elle ne confonde pas deux pairs.
        await portail.pool.execute("UPDATE enrolment_peer SET base_url = $1", "http://autre")

        etat = await portail.client.get("/api/git-connections/confided")

        assert etat.json()["peer_base_url"] == "http://autre"
        assert etat.json()["transmitted_at"] is None
        assert etat.json()["up_to_date"] is False


async def _event(portail: PortalStack, event_type: str) -> dict[str, Any]:
    row = await portail.pool.fetchrow(
        "SELECT properties FROM events WHERE type = $1 ORDER BY written_at DESC LIMIT 1",
        event_type,
    )
    assert row is not None, f"aucun event {event_type}"
    charge: dict[str, Any] = json.loads(row["properties"])
    return charge


async def _aucun_credential_au_journal(portail: PortalStack) -> None:
    """Le journal est lu bien plus largement que la table des connexions : rien n'y passe."""
    rows = await portail.pool.fetch("SELECT type, properties FROM events")
    ecrit = json.dumps([dict(r) for r in rows], default=str)
    assert CREDENTIAL not in ecrit
    assert RENOUVELE not in ecrit
