from __future__ import annotations

import pytest

from miles.oidc.model import (
    ConnectorInput,
    ConnectorInputError,
    validate_connector_id,
    validate_input,
    validate_issuer,
    validate_scopes,
)

RAW = ConnectorInput(
    issuer="https://security.example.org/realms/miles",
    client_id=" miles ",
    client_secret_slug="kc-secret",
    scopes="openid email profile email",
    active=True,
    labels={"en-US": " Keycloak ", "fr-FR": ""},
)


def test_valid_input_is_normalised() -> None:
    data = validate_input(RAW, allow_http=False)

    assert (data.client_id, data.scopes) == ("miles", "openid email profile")
    assert data.labels == {"en-US": "Keycloak", "fr-FR": ""}


@pytest.mark.parametrize(
    "issuer",
    [
        "http://security.example.org/realms/miles",
        "ftp://security.example.org",
        "https://user:pw@security.example.org",
        "https://security.example.org/realms/miles?x=1",
        "https://security.example.org/#frag",
        "https://",
        "pas une url",
    ],
)
def test_issuer_must_be_a_plain_https_url(issuer: str) -> None:
    with pytest.raises(ConnectorInputError) as caught:
        validate_issuer(issuer, allow_http=False)
    assert caught.value.field == "issuer"


def test_http_issuer_is_accepted_only_when_explicitly_allowed() -> None:
    assert validate_issuer("http://oidc:8080/miles", allow_http=True) == "http://oidc:8080/miles"


@pytest.mark.parametrize("scopes", ["email profile", "", "openid bad scope!"])
def test_scopes_must_include_openid_and_stay_simple(scopes: str) -> None:
    with pytest.raises(ConnectorInputError, match="scopes"):
        validate_scopes(scopes)


@pytest.mark.parametrize(
    ("field", "override"),
    [
        ("client_id", {"client_id": "  "}),
        ("label", {"labels": {"fr-FR": "Clé"}}),
        ("label", {"labels": {"en-US": "  "}}),
        ("labels", {"labels": {"en-US": "K", "pas une culture": "x"}}),
        ("labels", {"labels": {"en-US": "K" * 201}}),
        ("client_secret_slug", {"client_secret_slug": ""}),
    ],
)
def test_incomplete_input_names_the_field(field: str, override: dict[str, str]) -> None:
    raw = ConnectorInput(**{**RAW.__dict__, **override})

    with pytest.raises(ConnectorInputError) as caught:
        validate_input(raw, allow_http=False)
    assert caught.value.field == field


@pytest.mark.parametrize("connector_id", ["", "a", "Keycloak", "kc_1", "-kc", "a" * 64])
def test_connector_id_shape(connector_id: str) -> None:
    with pytest.raises(ConnectorInputError, match="id"):
        validate_connector_id(connector_id)
