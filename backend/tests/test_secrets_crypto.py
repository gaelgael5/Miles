from __future__ import annotations

import base64
import os

import pytest

from miles.secrets.crypto import (
    KEY_ENTRY,
    KEY_VERSION,
    Sealed,
    SecretCipher,
    SecretsKeyError,
    parse_secrets_key,
)
from miles.secrets.model import Secret, SecretUndecipherableError

VALUE = Secret("jeton-github-tres-secret")


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def test_parse_secrets_key_decodes_32_url_safe_bytes() -> None:
    raw = os.urandom(32)

    assert parse_secrets_key(_encoded(raw) + "\n") == raw


@pytest.mark.parametrize(
    "raw",
    ["", "pas du base64 !", _encoded(os.urandom(16)), _encoded(os.urandom(33)), "YWJj*="],
)
def test_parse_secrets_key_refuses_bad_keys_without_echoing_them(raw: str) -> None:
    with pytest.raises(SecretsKeyError) as caught:
        parse_secrets_key(raw)

    assert KEY_ENTRY in str(caught.value)
    if raw:
        assert raw not in str(caught.value)


def test_cipher_round_trips_and_never_stores_the_clear_value() -> None:
    cipher = SecretCipher(os.urandom(32))

    sealed = cipher.seal("git-token", VALUE)

    assert VALUE.reveal().encode() not in sealed.ciphertext
    assert sealed.key_version == KEY_VERSION
    assert cipher.open("git-token", sealed) == VALUE


def test_cipher_uses_a_fresh_nonce_for_each_seal() -> None:
    cipher = SecretCipher(os.urandom(32))

    first, second = cipher.seal("a1", VALUE), cipher.seal("a1", VALUE)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_ciphertext_moved_to_another_slug_does_not_open() -> None:
    cipher = SecretCipher(os.urandom(32))
    sealed = cipher.seal("git-token", VALUE)

    with pytest.raises(SecretUndecipherableError) as caught:
        cipher.open("oidc-secret", sealed)
    assert caught.value.slug == "oidc-secret"


def test_wrong_key_fails_explicitly_instead_of_returning_garbage() -> None:
    sealed = SecretCipher(os.urandom(32)).seal("git-token", VALUE)

    with pytest.raises(SecretUndecipherableError):
        SecretCipher(os.urandom(32)).open("git-token", sealed)


def test_tampered_ciphertext_and_unknown_key_version_are_refused() -> None:
    cipher = SecretCipher(os.urandom(32))
    sealed = cipher.seal("git-token", VALUE)
    tampered = Sealed(
        sealed.key_version, sealed.nonce, bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]
    )

    with pytest.raises(SecretUndecipherableError):
        cipher.open("git-token", tampered)
    with pytest.raises(SecretUndecipherableError):
        cipher.open("git-token", Sealed(KEY_VERSION + 1, sealed.nonce, sealed.ciphertext))


def test_cipher_refuses_a_key_of_the_wrong_length() -> None:
    with pytest.raises(SecretsKeyError):
        SecretCipher(os.urandom(16))
