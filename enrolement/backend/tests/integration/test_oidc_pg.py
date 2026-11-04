from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from miles_socle.auth.sessions import SESSION_COOKIE

from tests.integration.enrolement_stack import EnrolementStack, open_stack

pytestmark = pytest.mark.integration

PUBLIC_URL = "http://enrolement.test"
CLIENT_ID = "miles-client"  # aud des jetons, configuré dans le mock par le script
CLIENT_SECRET = "secret-client-du-mock"  # valeur du fournisseur jetable
# L'e-mail du compte d'amorçage est celui que le fournisseur jetable met dans ses jetons,
# en d'autres capitales : la reconnaissance ne dépend que de la casse de l'adresse.
ADMIN_EMAIL = "ALICE@example.org"


def _issuer() -> str:
    # Posé par scripts/run-integration-tests.sh, qui lance un vrai fournisseur OIDC
    # jetable (mock-oauth2-server) : c'est le parcours complet qu'on éprouve, pas une
    # doublure écrite par nous.
    base = os.environ.get("MILES_TEST_OIDC_URL")
    if not base:
        pytest.fail("MILES_TEST_OIDC_URL absent : lancer via scripts/run-integration-tests.sh")
    return f"{base}/miles"


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[EnrolementStack]:
    async with open_stack(
        blank_db, tmp_path, admin_email=ADMIN_EMAIL, public_url=PUBLIC_URL
    ) as monte:
        cree = await monte.client.post(
            "/api/secrets",
            json={
                "slug": "mock-secret",
                "label": "Mock",
                "secret_type": "OIDC_CLIENT_SECRET",
                "value": CLIENT_SECRET,
            },
        )
        assert cree.status_code == 201
        yield monte


async def _declare(stack: EnrolementStack, **overrides: object) -> httpx.Response:
    body = {
        "id": "mock",
        "labels": {"en-US": "Annuaire de test"},
        "issuer": _issuer(),
        "client_id": CLIENT_ID,
        "client_secret_slug": "mock-secret",
    } | overrides
    return await stack.client.post("/api/oidc/connectors", json=body)


async def test_un_connecteur_se_declare_et_son_secret_client_n_est_jamais_restitue(
    stack: EnrolementStack,
) -> None:
    assert (await _declare(stack)).status_code == 201

    liste = await stack.client.get("/api/oidc/connectors")

    assert liste.status_code == 200
    (connecteur,) = liste.json()
    assert connecteur["client_secret_slug"] == "mock-secret"
    # Le secret lui-même ne sort par aucune route : seul son slug circule.
    assert CLIENT_SECRET not in liste.text
    detail = await stack.client.get("/api/secrets")
    assert CLIENT_SECRET not in detail.text


async def test_un_connecteur_sert_une_connexion_de_bout_en_bout(
    stack: EnrolementStack,
) -> None:
    assert (await _declare(stack, recognize_admin=True)).status_code == 201
    visiteur = stack.anonymous()

    # 1. L'écran de connexion liste les connecteurs actifs, sans session.
    proposes = await visiteur.get("/api/auth/oidc/connectors", params={"culture": "en-US"})
    assert proposes.status_code == 200
    assert [c["id"] for c in proposes.json()] == ["mock"]

    # 2. Le navigateur part chez le fournisseur…
    depart = await visiteur.get("/api/auth/oidc/start", params={"connector": "mock"})
    assert depart.status_code == 303
    retour = await stack.http.get(depart.headers["location"])
    cible = retour.headers["location"]
    assert cible.startswith(f"{PUBLIC_URL}/api/auth/oidc/callback?")
    parametres = {k: v[0] for k, v in parse_qs(urlsplit(cible).query).items()}

    # 3. …et en revient avec un code, que le produit échange contre des jetons signés.
    ouverte = await visiteur.get("/api/auth/oidc/callback", params=parametres)

    assert ouverte.status_code == 303
    moi = await visiteur.get("/api/auth/me")
    assert moi.status_code == 200
    assert moi.json()["kind"] == "oidc"
    assert moi.json()["directory"] == "mock"
    # Reconnu administrateur parce que son e-mail est celui du compte d'amorçage ET que
    # la case du connecteur l'autorise. Les deux sont nécessaires.
    assert moi.json()["root_admin"] is True
    await visiteur.aclose()


async def test_sans_la_case_de_reconnaissance_la_session_oidc_n_a_aucun_droit(
    stack: EnrolementStack,
) -> None:
    # recognize_admin est décochée par défaut : aucun pouvoir sans décision explicite.
    assert (await _declare(stack)).status_code == 201
    visiteur = stack.anonymous()

    depart = await visiteur.get("/api/auth/oidc/start", params={"connector": "mock"})
    retour = await stack.http.get(depart.headers["location"])
    parametres = {k: v[0] for k, v in parse_qs(urlsplit(retour.headers["location"]).query).items()}
    assert (await visiteur.get("/api/auth/oidc/callback", params=parametres)).status_code == 303

    moi = await visiteur.get("/api/auth/me")
    assert moi.json()["root_admin"] is False
    # Authentifié n'est pas autorisé : aucun accès par défaut.
    assert (await visiteur.get("/api/oidc/connectors")).status_code == 403
    assert (await visiteur.get("/api/cultures")).status_code == 403
    # Ses propres préférences, en revanche, ne concernent qu'elle.
    assert (await visiteur.get("/api/auth/me/preferences")).status_code == 200
    await visiteur.aclose()


async def test_un_connecteur_dont_le_secret_est_encore_utilise_protege_ce_secret(
    stack: EnrolementStack,
) -> None:
    assert (await _declare(stack)).status_code == 201

    refus = await stack.client.delete("/api/secrets/mock-secret")

    # RESTRICT en base : le secret ne disparaît pas sous le connecteur qui s'en sert.
    assert refus.status_code == 409


async def test_le_cookie_d_etat_de_la_connexion_oidc_ne_porte_pas_de_domaine_parent(
    stack: EnrolementStack,
) -> None:
    assert (await _declare(stack)).status_code == 201
    visiteur = stack.anonymous()

    depart = await visiteur.get("/api/auth/oidc/start", params={"connector": "mock"})

    pose = depart.headers["set-cookie"]
    assert "domain=" not in pose.lower()
    assert "httponly" in pose.lower()
    await visiteur.aclose()


async def test_une_session_locale_reste_valable_apres_declaration_d_un_connecteur(
    stack: EnrolementStack,
) -> None:
    assert (await _declare(stack)).status_code == 201

    # Le compte d'amorçage garde l'administration racine quelles que soient les règles.
    moi = await stack.client.get("/api/auth/me")

    assert moi.json()["kind"] == "local_admin"
    assert moi.json()["root_admin"] is True
    assert SESSION_COOKIE in stack.client.cookies
