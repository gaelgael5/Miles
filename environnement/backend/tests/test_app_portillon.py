"""Le PORTILLON : ce qui est refusé, et les deux listes de passage qui en dispensent.

Rangé à part le 3 novembre 2026 (enabler `82ec7d76`). `signed_api_paths` et
`system_api_paths` sont DISTINCTES, et chacune est comparée ici à une égalité écrite en
dur : ouvrir un chemin de plus doit obliger quelqu'un à venir le dire, plutôt que de
passer inaperçu.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from miles_socle.auth.sessions import SESSION_COOKIE
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.pairing.api_peer import router as peer_router
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER
from miles_socle.signing.hosting import HOSTED_VERSION_PATH
from miles_socle.signing.protocol import PAIRING_REVOKED_PATH

from environnement.app import build_app
from environnement.hosting.api_peer_hosting import router as peer_hosting_router
from environnement.identity.service import PEER_PING_PATH


def test_une_route_sans_session_est_refusee(client_avec_admin: TestClient) -> None:
    reponse = client_avec_admin.get("/api/cultures")

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "session_requise"}


def test_un_cookie_de_session_d_un_autre_produit_est_refuse(
    client_avec_admin: TestClient,
) -> None:
    # Un jeton valide ailleurs n'a pas d'empreinte dans CETTE base : refusé.
    client_avec_admin.cookies.set(SESSION_COOKIE, "jeton-ouvert-sur-un-autre-produit")

    reponse = client_avec_admin.get("/api/cultures")

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "session_requise"}


@pytest.mark.parametrize(
    "chemin",
    [
        "/api/secrets",
        "/api/oidc/connectors",
        "/api/auth/me",
        "/api/auth/me/preferences",
    ],
)
def test_aucune_route_de_gestion_n_est_atteignable_sans_session(
    client_avec_admin: TestClient, chemin: str
) -> None:
    # Fail closed : la passerelle ne connaît qu'une liste blanche, et ces routes n'y sont pas.
    assert client_avec_admin.get(chemin).status_code == 401


def test_les_routes_de_l_identite_exigent_une_session(client_avec_admin: TestClient) -> None:
    # Elles montrent la clé publique, déclarent le pair et DÉCLENCHENT l'appariement :
    # rien de tout cela n'est public. Une route d'appariement ouverte laisserait un
    # inconnu faire frapper ce module chez un enrôlement qu'il aurait choisi.
    assert client_avec_admin.get("/api/identity").status_code == 401
    assert client_avec_admin.get("/api/identity/peer").status_code == 401
    assert client_avec_admin.put("/api/identity/peer", json={}).status_code == 401
    assert client_avec_admin.post("/api/identity/peer/ping").status_code == 401
    assert client_avec_admin.get("/api/identity/pairing").status_code == 401
    assert client_avec_admin.post("/api/identity/pairing", json={}).status_code == 401
    assert client_avec_admin.post("/api/identity/pairing/confirm", json={}).status_code == 401
    assert client_avec_admin.delete("/api/identity/pairing").status_code == 401


def test_la_route_de_pair_est_declaree_au_portillon_depuis_son_propre_routeur() -> None:
    """La garde du ticket : chemin ouvert et vérification de signature viennent d'un seul lieu.

    Le portillon ne laisse passer que ce que `peer_router` porte. Si quelqu'un ouvrait un
    chemin à la main sans la route qui vérifie, cette égalité tomberait — et c'est
    exactement la panne qu'on refuse : une route ouverte à tous, verte partout.
    """
    app = build_app()

    assert app.state.signed_api_paths == frozenset(
        route.path
        for routeur in (peer_router, peer_hosting_router)
        for route in routeur.routes
        if isinstance(route, APIRoute)
    )
    # DEUX chemins ouverts depuis le 29/10/2026, et le second est le sens inverse du
    # premier : l'enrôlement nous POUSSE l'avis qu'il nous a révoqué l'accès. Cette
    # égalité est écrite en dur exprès — ouvrir un chemin de plus doit obliger quelqu'un
    # à venir le dire ici, plutôt que de passer inaperçu.
    # TROIS depuis le 01/11/2026 : l'enrôlement nous POUSSE l'ordre de servir une
    # version (story 3bbd4f87), et ce chemin-là écrit sur notre volume. La décision
    # que ce rouge force à prendre : il n'est ouvert que parce que la signature du
    # module d'enrôlement apparié y est vérifiée avant toute lecture du corps.
    assert app.state.signed_api_paths == {
        PEER_PING_PATH,
        PAIRING_REVOKED_PATH,
        HOSTED_VERSION_PATH,
    }


def test_un_appel_de_pair_non_signe_est_refuse(client_avec_admin: TestClient) -> None:
    # La route passe le portillon — elle est faite pour être appelée sans session — et
    # c'est ELLE qui refuse. Sans pair apparié, il n'y a même pas de clé pour vérifier.
    reponse = client_avec_admin.post(PEER_PING_PATH, json={})

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "signature_refusee"}


def test_le_refus_d_un_appel_de_pair_ne_dit_pas_ce_qui_peche(
    client_avec_admin: TestClient,
) -> None:
    # Dire si c'est l'en-tête, l'origine ou la signature offrirait un oracle pour
    # approcher l'une par l'autre. La raison précise va au journal, pas à l'appelant.
    refus = {
        client_avec_admin.post(PEER_PING_PATH, json={}, headers=entetes).json()["detail"]
        for entetes in (
            {},
            {ORIGIN_HEADER: "https://enrolement.test"},
            {ORIGIN_HEADER: "https://enrolement.test", SIGNATURE_HEADER: "v1 " + "A" * 86},
            {ORIGIN_HEADER: "pas-une-origine", SIGNATURE_HEADER: "v1 " + "A" * 86},
        )
    }

    assert refus == {"signature_refusee"}


def test_la_route_d_entretien_des_journaux_est_LA_SEULE_ouverte_par_secret_de_stack() -> None:
    """Deux listes de passage, et une seule route dans la seconde.

    `system_api_paths` est distincte de `signed_api_paths` : une signature prouve l'identité
    d'un pair par une clé échangée à l'appariement, un secret de stack ne prouve que
    l'appartenance à la stack. Cette égalité est écrite en dur exprès — ouvrir un second
    chemin par secret de stack doit obliger quelqu'un à venir le dire ici.
    """
    app = build_app()

    assert app.state.system_api_paths == {MAINTENANCE_PATH}
    # Le jeton, lui, est posé par la durée de vie et non par la construction : qu'il soit
    # nul par défaut — route inerte — est éprouvé par la suite du socle, qui monte la route
    # sans jeton, et par les tests d'intégration sur une base réelle.
