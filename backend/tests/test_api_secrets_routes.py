from __future__ import annotations

from miles.app import build_app


def test_no_route_serves_a_secret_value() -> None:
    # La résolution est réservée au serveur : aucune route sous /api/secrets ne la sert.
    # La spec générée liste ce que l'application sert réellement.
    paths = build_app().openapi()["paths"]
    routes = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/secrets")
        for method in operations
    }
    assert routes == {
        ("GET", "/api/secrets"),
        ("POST", "/api/secrets"),
        ("GET", "/api/secrets/{slug}"),
        ("PATCH", "/api/secrets/{slug}"),
        ("PUT", "/api/secrets/{slug}/value"),
        ("DELETE", "/api/secrets/{slug}"),
    }
