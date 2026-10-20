from __future__ import annotations

import pytest

from miles.secrets.model import (
    MAX_LABEL_LENGTH,
    MAX_VALUE_LENGTH,
    Consumer,
    Secret,
    SecretInputError,
    validate_consumer,
    validate_label,
    validate_secret_type,
    validate_slug,
    validate_value,
)

VALUE = "s3cr3t-valeur-discriminante"


def test_secret_repr_and_str_never_show_the_value() -> None:
    secret = Secret(VALUE)

    assert VALUE not in repr(secret)
    assert VALUE not in str(secret)
    assert VALUE not in f"{secret} {secret!r}"
    assert secret.reveal() == VALUE


def test_secret_equality_compares_values_without_exposing_them() -> None:
    assert Secret(VALUE) == Secret(VALUE)
    assert Secret(VALUE) != Secret(VALUE + "x")
    assert len({Secret(VALUE), Secret(VALUE)}) == 1


@pytest.mark.parametrize("slug", ["ab", "keycloak-root", "a1", "0-git-token", "a" * 63])
def test_validate_slug_accepts_lowercase_dash_slugs(slug: str) -> None:
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", ["", "a", "-ab", "Ab", "a_b", "a b", "a/b", "../x", "a" * 64, "é-a"]
)
def test_validate_slug_rejects_other_shapes_naming_the_field(slug: str) -> None:
    with pytest.raises(SecretInputError) as caught:
        validate_slug(slug)
    assert caught.value.field == "slug"


def test_validate_label_trims_and_bounds_length() -> None:
    assert validate_label("  Secret OIDC  ") == "Secret OIDC"
    for label in ["", "   ", "x" * (MAX_LABEL_LENGTH + 1)]:
        with pytest.raises(SecretInputError) as caught:
            validate_label(label)
        assert caught.value.field == "label"


@pytest.mark.parametrize("secret_type", ["OIDC_CLIENT_SECRET", "GIT_TOKEN", "A1"])
def test_validate_secret_type_accepts_uppercase_names(secret_type: str) -> None:
    assert validate_secret_type(secret_type) == secret_type


@pytest.mark.parametrize("secret_type", ["", "A", "git_token", "1ABC", "GIT-TOKEN"])
def test_validate_secret_type_rejects_other_shapes(secret_type: str) -> None:
    with pytest.raises(SecretInputError) as caught:
        validate_secret_type(secret_type)
    assert caught.value.field == "secret_type"


def test_validate_value_wraps_the_value_in_an_opaque_secret() -> None:
    secret = validate_value(VALUE)

    assert isinstance(secret, Secret)
    assert secret.reveal() == VALUE


@pytest.mark.parametrize(
    "value",
    [
        "",
        "${local://git-token}",
        "${vault://perso:apikey}",
        "  ${x}  ",
        "x" * (MAX_VALUE_LENGTH + 1),
    ],
)
def test_validate_value_rejects_empty_oversized_and_indirections(value: str) -> None:
    with pytest.raises(SecretInputError) as caught:
        validate_value(value)
    assert caught.value.field == "value"
    assert value not in str(caught.value) or value == ""


def test_validate_value_accepts_dollar_text_that_is_not_an_indirection() -> None:
    assert validate_value("pa$${word").reveal() == "pa$${word"


def test_validate_consumer_checks_kind_and_id() -> None:
    assert validate_consumer(Consumer("oidc.connector", "keycloak")) == Consumer(
        "oidc.connector", "keycloak"
    )
    with pytest.raises(SecretInputError, match="consumer_kind"):
        validate_consumer(Consumer("Bad Kind", "x"))
    with pytest.raises(SecretInputError, match="consumer_id"):
        validate_consumer(Consumer("workspace", ""))
