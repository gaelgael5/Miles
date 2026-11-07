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
from environnement.ingestion.api_ingest_file import INGEST_FILE_PATH
from environnement.ingestion.model import MAX_BODY_BYTES

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

    **Il y en a DEUX depuis le 04/11/2026** (story `0f14adbd`) : le mode gros fichier a son
    chemin littéral, parce qu'il relaie le corps vers le disque au lieu de le lire, et
    qu'il n'accuse que la prise en charge. Il est protégé par EXACTEMENT la même garde —
    `resolve_caller`, partagée, avant d'écrire un seul octet — et un test l'affirme pour
    lui aussi.
    """
    hors_portillon = {chemin for chemin in chemins_servis() if not chemin.startswith("/api/")}

    assert hors_portillon == {INGEST_PATH, INGEST_FILE_PATH}


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


def _blocs_nginx() -> dict[str, str]:
    """Les `location` de la configuration, le modificateur d'expression régulière compris.

    Le motif de `test_les_routes_hors_api_sont_relayees_par_nginx` ne les capture pas :
    il attend l'accolade juste après le chemin, et `location ~ ^/api/… {` porte son
    modificateur avant. Deux motifs plutôt qu'un seul retouché, parce que l'autre garde
    éprouve autre chose et qu'élargir son motif l'aurait rendue muette sur son vrai sujet.
    """
    conf = NGINX.read_text(encoding="utf-8")
    return dict(re.findall(r"location\s+(?:~\s*)?(\S+)\s*\{([^}]*)\}", conf, re.DOTALL))


def test_les_chemins_de_depot_ne_gardent_pas_le_defaut_d_un_megaoctet_de_nginx() -> None:
    """Le défaut de `client_max_body_size` est 1 Mio, et il refusait TOUT dépôt réel.

    Mesuré le 07/11/2026 sur la stack livrée (bug `abc1b595`) : 1 049 000 octets sur
    `/ingest/` rendaient un 413 en HTML, le backend ne voyait jamais la requête, et les
    2 Gio que le contrat publié annonce étaient donc inatteignables par le port publié.
    Aucun test ne pouvait le voir — ils montent l'application ASGI, jamais le proxy —,
    d'où cette garde, qui lit la configuration plutôt que le comportement.

    `0` et non une grande valeur : c'est l'APPLICATION qui borne, sur
    `ingestion_file_max_bytes` et sur le quota du storage, et c'est son refus — avec son
    code et sa borne dans `detail` — que l'appelant doit lire.
    """
    blocs = _blocs_nginx()

    for chemin in ("/ingest/", "^/api/ingestion/try/"):
        assert chemin in blocs, f"aucun bloc nginx pour {chemin}"
        assert "client_max_body_size 0;" in blocs[chemin], (
            f"le bloc {chemin} garde une borne de taille : le port publié refusera un"
            " dépôt réel avant que le backend ne le voie"
        )
        # Sans cela, nginx accumule le document entier sur son disque avant d'en passer
        # un octet au backend : la barre de progression de l'écran monterait à 100 % puis
        # se figerait pendant toute l'écriture réelle.
        assert "proxy_request_buffering off;" in blocs[chemin], (
            f"le bloc {chemin} met le corps en tampon"
        )


def test_le_plafond_nginx_de_l_api_reste_AU_DESSUS_de_la_borne_applicative() -> None:
    """nginx est un plafond contre l'abus, l'application est la borne qui PARLE.

    Les deux doivent rester dans cet ordre : si le plafond de nginx descendait au niveau de
    `MAX_BODY_BYTES` ou en dessous, c'est sa page HTML que l'appelant lirait au lieu du
    refus `corps_trop_grand` avec sa borne dedans. Et deux valeurs égales auraient fait de
    nginx une seconde source de vérité sur la borne métier, que le premier relèvement fait
    d'un seul côté aurait désaccordée.
    """
    bloc = _blocs_nginx()["/api/"]
    trouve = re.search(r"client_max_body_size\s+(\d+)m\s*;", bloc)

    assert trouve is not None, "le bloc /api/ ne déclare aucun plafond de taille"
    assert int(trouve.group(1)) * 1024 * 1024 > MAX_BODY_BYTES


def test_chaque_bloc_qui_relaie_porte_les_memes_en_tetes() -> None:
    """Trois blocs mandatent, et un seul fichier porte leurs en-têtes.

    `X-Real-IP` est écrasé là pour que le backend ne puisse pas le voir forgé : il s'en
    sert pour freiner les échecs de connexion par origine. Une copie oubliée dans un seul
    des trois blocs lui ferait compter toutes les origines comme une — et c'est le genre
    d'oubli qui ne casse rien de visible.
    """
    inclusion = "include /etc/nginx/proxy.conf;"
    mandataires = {nom: corps for nom, corps in _blocs_nginx().items() if "proxy_pass" in corps}

    assert len(mandataires) == 3, mandataires.keys()
    for nom, corps in mandataires.items():
        assert inclusion in corps, f"le bloc {nom} ne porte pas les en-têtes communes"
    # Le fichier inclus DOIT être copié dans l'image : un `include` qui ne résout pas est
    # une erreur FATALE au démarrage de nginx, donc le front ne servirait plus rien.
    frontend = NGINX.parent
    assert (frontend / "proxy.conf").is_file()
    assert "COPY proxy.conf /etc/nginx/proxy.conf" in (frontend / "Dockerfile").read_text(
        encoding="utf-8"
    )
