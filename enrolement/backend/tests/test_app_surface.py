"""La SURFACE servie : les chemins exposés, et ce qui ne doit pas l'être.

Rangé à part le 3 novembre 2026 (enabler `82ec7d76`). La liste est écrite en dur exprès :
une route du socle oubliée au montage donne un écran qui appelle dans le vide, sans que
rien ne soit rouge.
"""

from __future__ import annotations

from enrolement.app import build_app

from .app_harness import chemins_servis


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


def test_la_documentation_interactive_n_est_pas_servie() -> None:
    # /docs et /openapi.json seraient des routes ouvertes hors de la passerelle.
    app = build_app()

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert "/docs" not in chemins_servis()
