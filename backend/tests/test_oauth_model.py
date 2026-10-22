from __future__ import annotations

import pytest

from miles.oauth.model import checked_redirect_uri, pkce_matches, same_resource

# RFC 7636, annexe B : vecteur de la spécification, rejoué tel quel.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_s256_matches_the_rfc_vector() -> None:
    assert pkce_matches(VERIFIER, CHALLENGE)


@pytest.mark.parametrize(
    "verifier",
    [VERIFIER[:-1] + "x", "court", VERIFIER + " ", "é" * 43, ""],
)
def test_pkce_refuses_any_other_or_malformed_verifier(verifier: str) -> None:
    assert not pkce_matches(verifier, CHALLENGE)


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "http://localhost:6274/oauth/callback",
        "http://127.0.0.1/cb",
    ],
)
def test_https_or_loopback_return_addresses_are_accepted(uri: str) -> None:
    assert checked_redirect_uri(f"  {uri} ") == uri


@pytest.mark.parametrize(
    "uri",
    [
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai/cb#fragment",
        "javascript:alert(1)",
        "https:///sans-hote",
        "ftp://claude.ai/cb",
        "https://claude.ai/" + "x" * 300,
    ],
)
def test_other_return_addresses_are_refused(uri: str) -> None:
    with pytest.raises(ValueError):
        checked_redirect_uri(uri)


def test_resource_ignores_only_the_trailing_slash() -> None:
    assert same_resource("https://m.exemple/mcp", "https://m.exemple/mcp/")
    assert not same_resource("https://autre.exemple/mcp/", "https://m.exemple/mcp/")
