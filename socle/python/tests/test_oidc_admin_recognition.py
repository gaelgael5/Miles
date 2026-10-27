from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from miles_socle.events.model import EventTypeCatalog
from miles_socle.oidc.model import Connector
from miles_socle.oidc.provider import Identity
from miles_socle.oidc.service import OidcService

ADMIN = "Admin@Miles.example"
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _connector(recognize_admin: bool) -> Connector:
    return Connector(
        id="kc",
        issuer="https://idp.example.org",
        client_id="miles",
        client_secret_slug="s",
        scopes="openid",
        active=True,
        label="KC",
        groups_claim="groups",
        display_name_claim="name",
        recognize_admin=recognize_admin,
        manage_associations=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _service(admin_email: str | None) -> OidcService:
    unused: Any = None
    return OidcService(
        unused, unused, unused, EventTypeCatalog(), lambda: NOW, None, False, lambda: admin_email
    )


@pytest.mark.parametrize(
    ("recognize", "admin_email", "email", "expected"),
    [
        (True, ADMIN, ADMIN, True),
        (True, ADMIN, "admin@miles.EXAMPLE", True),  # insensible à la casse
        (False, ADMIN, ADMIN, False),  # case décochée : jamais
        (True, ADMIN, "autre@miles.example", False),
        (True, ADMIN, None, False),  # e-mail absent du jeton : pas une erreur
        (True, None, ADMIN, False),  # aucun compte d'amorçage : rien à comparer
        (True, "", "", False),  # jamais de comparaison avec une valeur vide
        (True, ADMIN, f" {ADMIN}", False),  # aucune autre normalisation que la casse
        (True, ADMIN, "admin@miles.example.evil.org", False),
    ],
)
def test_admin_recognition_needs_the_box_and_the_exact_email(
    recognize: bool, admin_email: str | None, email: str | None, expected: bool
) -> None:
    service = _service(admin_email)

    recognized = service._recognizes_admin(_connector(recognize), Identity("sub-1", "Alice", email))

    assert recognized is expected
