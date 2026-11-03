"""La SURFACE servie : les chemins exposés, et ce qui doit les relayer ou les taire.

Rangé à part le 3 novembre 2026 (enabler `82ec7d76`). Chaque garde d'ici compare la
surface de l'application à une déclaration faite AILLEURS — une liste écrite en dur, le
`nginx.conf` du front — parce qu'une surface déclarée à deux endroits qui ne se parlent
pas ne se tient que par une garde qui les confronte.
"""

from __future__ import annotations

import re

from miles_socle.pairing.api_peer import PEER_PING_PATH

from environnement.app import build_app
from environnement.ingestion.api_ingest import INGEST_PATH

from .app_harness import NGINX, chemins_servis


def test_les_routes_du_socle_sont_toutes_montees() -> None:
    chemins = chemins_servis()

    # Le pendant de la garde « écran déclaré au routage mais absent du menu » : une route
    # oubliée ici donne un écran qui appelle dans le vide, sans que rien ne soit rouge.
    assert {
        "/api/health",
        "/api/bootstrap",
        "/api/bootstrap/status",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/me/preferences",
        "/api/auth/cultures",
        "/api/auth/oidc/connectors",
        "/api/auth/oidc/start",
        "/api/auth/oidc/callback",
        "/api/cultures",
        "/api/cultures/active",
        "/api/cultures/activation",
        "/api/secrets",
        "/api/secret-types",
        "/api/oidc/connectors",
    } <= chemins


def test_les_routes_de_l_identite_sont_montees() -> None:
    chemins = chemins_servis()

    assert {
        "/api/identity",
        "/api/identity/peer",
        "/api/identity/peer/ping",
        PEER_PING_PATH,
    } <= chemins


def test_la_SEULE_route_hors_du_portillon_est_le_point_d_entree_d_ingestion() -> None:
    """La garde d'une famille neuve : une route hors de `/api` n'est gardée par PERSONNE.

    La passerelle d'authentification ne regarde que `/api` — c'est écrit dans sa première
    ligne. Toute route posée ailleurs est donc ouverte au réseau, et ne tient que par ce
    qu'elle vérifie elle-même. Le point d'entrée d'ingestion est dans ce cas, et c'est
    une décision : il est appelé de machine à machine, s'authentifie par clé d'API, et
    porte des paramètres de chemin que la liste blanche — qui compare des chemins exacts
    — ne saurait pas décrire.

    Cette égalité est écrite en dur exprès. Poser une seconde route hors de `/api` doit
    obliger quelqu'un à venir le dire ici, en écrivant par quoi elle est protégée. Sans
    cette garde, une route d'administration posée hors de `/api` par distraction serait
    ouverte à tous, et verte partout.
    """
    hors_portillon = {chemin for chemin in chemins_servis() if not chemin.startswith("/api/")}

    assert hors_portillon == {INGEST_PATH}


def test_toute_route_hors_de_l_API_est_RELAYEE_par_le_proxy() -> None:
    """La garde du défaut du 02/11/2026, que seule la livraison a révélé.

    Le `nginx.conf` du front est une **seconde déclaration de surface**, indépendante de
    celle de l'application : il relaie `/api/` au backend et sert tout le reste comme des
    fichiers statiques. Une route posée hors de `/api` tombe donc dans `location /`, où
    nginx refuse un POST par un **405 Not Allowed** — et le backend ne voit jamais la
    requête. Mesuré : le point d'entrée d'ingestion répondait 401 correctement en
    interne, et 405 sur le port publié.

    Aucun test ne pouvait le voir : tous montent l'application ASGI, aucun ne monte le
    proxy. Celui-ci lit le fichier de configuration, ce qui est la seule façon de
    confronter les deux déclarations sans déployer.
    """
    conf = NGINX.read_text(encoding="utf-8")
    blocs = {
        nom: corps for nom, corps in re.findall(r"location\s+(\S+)\s*\{([^}]*)\}", conf, re.DOTALL)
    }
    hors_api = {c for c in chemins_servis() if not c.startswith("/api/")}
    assert hors_api, "aucune route hors de /api : cette garde n'éprouverait rien"
    for chemin in hors_api:
        prefixe = f"/{chemin.split('/')[1]}/"
        assert prefixe in blocs, (
            f"{chemin} n'est relayée par aucun bloc nginx : le port publié rendra 405"
        )
        assert "proxy_pass" in blocs[prefixe], (
            f"le bloc nginx {prefixe} existe mais ne relaie rien au backend"
        )


def test_la_documentation_interactive_n_est_pas_servie() -> None:
    # /docs et /openapi.json seraient des routes ouvertes hors de la passerelle.
    app = build_app()

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert "/docs" not in chemins_servis()
