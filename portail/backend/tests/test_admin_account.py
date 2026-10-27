from __future__ import annotations

import pytest

from miles.auth.admin_account import (
    ADMIN_EMAIL_KEY,
    ADMIN_PASSWORD_HASH_KEY,
    ADMIN_USERNAME_KEY,
    AdminConfigError,
    InvalidAdminInputError,
    resolve_admin_account,
    validate_admin_identity,
)
from miles.auth.passwords import hash_password

HASH = hash_password("une phrase assez longue")


def _entries(**overrides: str) -> dict[str, str]:
    entries = {
        "MILES_DB_PASSWORD": "x",
        ADMIN_EMAIL_KEY: "gael@example.org",
        ADMIN_USERNAME_KEY: "admin",
        ADMIN_PASSWORD_HASH_KEY: HASH,
    }
    entries.update(overrides)
    return entries


def test_resolve_admin_account_no_entries_returns_none() -> None:
    assert resolve_admin_account({"MILES_DB_PASSWORD": "x"}) is None


def test_resolve_admin_account_all_empty_values_returns_none() -> None:
    entries = _entries(**{ADMIN_EMAIL_KEY: "", ADMIN_USERNAME_KEY: "", ADMIN_PASSWORD_HASH_KEY: ""})

    assert resolve_admin_account(entries) is None


def test_resolve_admin_account_complete_returns_account_with_masked_hash() -> None:
    account = resolve_admin_account(_entries())

    assert account is not None
    assert (account.email, account.username) == ("gael@example.org", "admin")
    assert account.password_hash.get_secret_value() == HASH
    assert HASH not in repr(account)


def test_resolve_admin_account_partial_refuses_to_start() -> None:
    entries = _entries()
    del entries[ADMIN_PASSWORD_HASH_KEY]

    with pytest.raises(AdminConfigError, match=r"incomplet.*MILES_ADMIN_PASSWORD_HASH.*\.env\.bak"):
        resolve_admin_account(entries)


def test_resolve_admin_account_truncated_hash_refuses_without_leaking_it() -> None:
    truncated = HASH[: len(HASH) // 2]

    with pytest.raises(AdminConfigError, match="argon2id") as caught:
        resolve_admin_account(_entries(**{ADMIN_PASSWORD_HASH_KEY: truncated}))

    assert truncated not in str(caught.value)


def test_resolve_admin_account_non_argon2id_hash_refuses() -> None:
    sha = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"

    with pytest.raises(AdminConfigError, match="argon2id"):
        resolve_admin_account(_entries(**{ADMIN_PASSWORD_HASH_KEY: sha}))


def test_resolve_admin_account_invalid_email_refuses() -> None:
    with pytest.raises(AdminConfigError, match="MILES_ADMIN_EMAIL"):
        resolve_admin_account(_entries(**{ADMIN_EMAIL_KEY: "pas-un-email"}))


@pytest.mark.parametrize(
    ("email", "username", "field"),
    [
        ("o'brien@example.org", "admin", "email"),
        ("a@b", "admin", "email"),
        ("gael@example.org", "Admin", "username"),
        ("gael@example.org", "ab", "username"),
        ("gael@example.org", "../etc", "username"),
    ],
)
def test_validate_admin_identity_rejects_unsafe_values(
    email: str, username: str, field: str
) -> None:
    with pytest.raises(InvalidAdminInputError, match=field):
        validate_admin_identity(email, username)
