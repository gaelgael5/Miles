from __future__ import annotations

import pytest

from miles.obo.signature import sign_actor, signed_actor

# Vecteur d'interopérabilité du contrat globals OBO v6 (d0e2dad3), rejoué tel quel.
SECRET = "shared-key-EXAMPLE"
ACTOR = "gael"
TIMESTAMP = 1763000000
EXPECTED = "6c1a34eb1b1ca3d9be66ea366460a397e5a684fa647f302368cc7237e8ec93ae"


def _headers(
    actor: str = ACTOR, timestamp: str = str(TIMESTAMP), signature: str = EXPECTED
) -> dict[str, str]:
    return {
        "x-portal-actor": actor,
        "x-portal-actor-timestamp": timestamp,
        "x-portal-actor-signature": signature,
    }


def test_interop_vector_signs_byte_for_byte() -> None:
    assert sign_actor(ACTOR, TIMESTAMP, SECRET) == EXPECTED


def test_interop_vector_is_accepted_within_the_window() -> None:
    assert signed_actor(_headers(), SECRET, TIMESTAMP + 299) == ACTOR
    assert signed_actor(_headers(), SECRET, TIMESTAMP - 299) == ACTOR


@pytest.mark.parametrize(
    ("headers", "secret", "now"),
    [
        (_headers(signature="0" * 64), SECRET, TIMESTAMP),
        (_headers(actor="quelquun"), SECRET, TIMESTAMP),
        (_headers(), "autre-cle", TIMESTAMP),
        (_headers(), SECRET, TIMESTAMP + 301),
        (_headers(), SECRET, TIMESTAMP - 301),
        (_headers(timestamp="-1"), SECRET, TIMESTAMP),
        (_headers(timestamp="1763000000.5"), SECRET, TIMESTAMP),
        ({"x-portal-actor": ACTOR}, SECRET, TIMESTAMP),
        ({}, SECRET, TIMESTAMP),
    ],
)
def test_forged_stale_or_partial_headers_are_ignored(
    headers: dict[str, str], secret: str, now: float
) -> None:
    assert signed_actor(headers, secret, now) is None
