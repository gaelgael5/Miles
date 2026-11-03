"""Le PORTILLON : ce qui est refusé, et les deux listes de passage qui en dispensent.

Rangé à part le 3 novembre 2026 (enabler `82ec7d76`). `signed_api_paths` et
`system_api_paths` sont DISTINCTES — une signature prouve l'identité d'un pair, un secret
de stack ne prouve que l'appartenance à la stack —, et chacune est comparée ici à une
égalité écrite en dur : ouvrir un chemin de plus doit obliger quelqu'un à venir le dire.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from miles_socle.auth.sessions import SESSION_COOKIE
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.signing.calls import ORIGIN_HEADER
from miles_socle.signing.hosting import HOSTING_BUNDLE_PATH
from miles_socle.signing.protocol import (
    GIT_CONNECTIONS_PATH,
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PEER_ENVIRONMENT_PATH,
    PEER_PING_PATH,
)

from enrolement.app import build_app
from enrolement.hosting.api_peer_hosting import router as peer_hosting_router
from enrolement.pairing.api_peer import router as peer_router


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


def test_seules_les_routes_de_pair_echappent_a_la_session() -> None:
    """La liste blanche des chemins signés est DÉRIVÉE du routeur qui les porte.

    Cette garde vérifie les deux moitiés : que la dérivation donne bien ce que le routeur
    porte, et que ce routeur ne porte QUE les routes du protocole. Sans la seconde,
    une route d'administration glissée dans ce routeur serait ouverte à tous — et la
    première assertion resterait verte.
    """
    app = build_app()

    assert app.state.signed_api_paths == frozenset(
        route.path
        for routeur in (peer_router, peer_hosting_router)
        for route in routeur.routes
        if isinstance(route, APIRoute)
    )
    assert app.state.signed_api_paths == {
        PEER_PING_PATH,
        PAIRING_REQUEST_PATH,
        PAIRING_CONFIRM_PATH,
        PAIRING_STATUS_PATH,
        # Ajoutée le 29/10/2026 : l'environnement apparié y lit à quel environnement du
        # référentiel il est rattaché. La liste est écrite À LA MAIN ici, et c'est tout
        # l'intérêt — elle a rougi à l'ajout de cette route, ce qui est exactement le
        # moment où quelqu'un doit décider qu'un chemin de plus échappe à la session.
        PEER_ENVIRONMENT_PATH,
        # Ajoutée le 30/10/2026 : le module de paramétrage apparié y confie ses connexions
        # git. Cette liste a rougi à son ajout, et c'est ce qu'on lui demande — un chemin
        # qui échappe à la session est une décision, et celle-ci porte des credentials.
        GIT_CONNECTIONS_PATH,
        # Ajoutée le 01/11/2026 : l'environnement apparié y vient CHERCHER le contenu de
        # la version qu'on lui a ordonnée (story 3bbd4f87). Cette liste a rougi à son
        # ajout, et c'est ce qu'on lui demande. La décision que ce rouge force à prendre :
        # ce chemin sert du contenu de dépôt sans session, et ce qu'il sert est borné par
        # l'ordre en base — SON workspace, au commit qu'on lui a ordonné, rien d'autre.
        HOSTING_BUNDLE_PATH,
    }


@pytest.mark.parametrize(
    "chemin", ["/api/pairing/requests", "/api/pairing/peers", "/api/pairing/identity"]
)
def test_les_routes_d_administration_de_l_appariement_exigent_une_session(
    client_avec_admin: TestClient, chemin: str
) -> None:
    # Elles listent les demandes et RENDENT LE CODE : les ouvrir donnerait à un inconnu
    # de quoi s'apparier sans qu'aucun humain ne l'ait voulu.
    assert client_avec_admin.get(chemin).status_code == 401


@pytest.mark.parametrize(
    ("chemin", "corps"),
    [
        (PEER_PING_PATH, {}),
        (PAIRING_REQUEST_PATH, {"public_key": "A" * 43, "name": "Recette"}),
        (PAIRING_CONFIRM_PATH, {"code": "123456"}),
        (PAIRING_STATUS_PATH, {}),
    ],
)
def test_un_appel_de_pair_non_signe_est_refuse_par_la_route(
    client_avec_admin: TestClient, chemin: str, corps: dict[str, str]
) -> None:
    # Ces routes passent le portillon — elles sont faites pour être appelées sans session
    # — et ce sont ELLES qui refusent. Le détail distingue le refus de la route de celui
    # du portillon (« session_requise »), sans quoi on ne saurait pas laquelle a parlé.
    #
    # L'appel est VALIDE partout ailleurs : corps bien formé, origine bien formée. Sans
    # cette précaution le test resterait vert pour la mauvaise raison — mesuré le
    # 28/10/2026 en retirant pour de vrai le contrôle de signature : l'absence d'origine
    # faisait refuser à sa place, et la garde ne prouvait que « quelque chose refuse ».
    #
    # CE QUE CE TEST NE PROUVE PAS, et il ne faut pas le lui faire dire : que la SIGNATURE
    # est vérifiée. La base est une doublure qui ne rend rien, donc plusieurs couches
    # refusent avant la cryptographie, et neutraliser le vérificateur laisse ce test vert.
    # La vérification elle-même est gardée par `tests/integration/test_appariement_pg.py`,
    # éprouvé en la neutralisant pour de vrai sur machine de test : trois tests rouges.
    reponse = client_avec_admin.post(
        chemin, json=corps, headers={ORIGIN_HEADER: "https://environnement.test"}
    )

    assert reponse.status_code == 401
    assert reponse.json()["detail"] != "session_requise"


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
