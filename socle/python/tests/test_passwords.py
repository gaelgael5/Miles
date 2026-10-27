from __future__ import annotations

import pytest

from miles_socle.auth.passwords import (
    WeakPasswordError,
    check_password_policy,
    hash_password,
    is_argon2id_hash,
    verify_password,
)


def test_check_password_policy_short_password_names_the_rule() -> None:
    with pytest.raises(WeakPasswordError, match="au moins 12") as caught:
        check_password_policy("onze-caract")

    assert (caught.value.rule, caught.value.limit) == ("min_length", 12)


def test_check_password_policy_too_long_names_the_rule() -> None:
    with pytest.raises(WeakPasswordError, match="au plus 256") as caught:
        check_password_policy("x" * 257)

    assert (caught.value.rule, caught.value.limit) == ("max_length", 256)


def test_check_password_policy_boundaries_accepted() -> None:
    check_password_policy("x" * 12)
    check_password_policy("x" * 256)


def test_hash_password_is_salted_argon2id_and_verifies() -> None:
    first, second = hash_password("phrase de passe"), hash_password("phrase de passe")

    assert first != second
    assert is_argon2id_hash(first)
    assert verify_password(first, "phrase de passe")
    assert not verify_password(first, "phrase de passE")


def test_is_argon2id_hash_rejects_argon2i_and_garbage() -> None:
    argon2i = "$argon2i$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2g"

    assert not is_argon2id_hash(argon2i)
    assert not is_argon2id_hash("$argon2id$tronqué")
