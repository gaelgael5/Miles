from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from miles.auth.admin_account import AdminConfigError, InvalidAdminInputError
from miles.auth.admin_store import AdminAccountStore
from miles.auth.env_file import EnvEntriesPresentError, EnvFileError, file_read_env
from miles.auth.passwords import WeakPasswordError, verify_password
from tests.auth_fixtures import ADMIN_PASSWORD, BASE_ENV, write_env


def test_file_load_without_admin_entries_has_no_account(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)

    assert AdminAccountStore.file_load(env, backup).account is None


def test_file_load_partial_account_refuses(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path, BASE_ENV + "MILES_ADMIN_EMAIL='a@example.org'\n")

    with pytest.raises(AdminConfigError):
        AdminAccountStore.file_load(env, backup)


def test_file_load_unreadable_env_refuses(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path, BASE_ENV + "MILES_ADMIN_EMA")

    with pytest.raises(EnvFileError):
        AdminAccountStore.file_load(env, backup)


async def test_resolve_declare_writes_hash_only_and_activates_account(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)
    store = AdminAccountStore.file_load(env, backup)

    account = await store.resolve_declare("gael@example.org", "admin", ADMIN_PASSWORD)

    written = env.read_text(encoding="utf-8")
    assert ADMIN_PASSWORD not in written
    assert written.startswith(BASE_ENV)
    assert store.account == account
    assert verify_password(account.password_hash.get_secret_value(), ADMIN_PASSWORD)
    # Relu depuis le disque : un nouveau processus voit le même compte.
    assert AdminAccountStore.file_load(env, backup).account == account
    assert backup.read_text(encoding="utf-8") == BASE_ENV


async def test_resolve_declare_weak_password_writes_nothing(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)
    store = AdminAccountStore.file_load(env, backup)

    with pytest.raises(WeakPasswordError):
        await store.resolve_declare("gael@example.org", "admin", "court")

    assert env.read_text(encoding="utf-8") == BASE_ENV
    assert store.account is None


async def test_resolve_declare_invalid_identity_writes_nothing(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)
    store = AdminAccountStore.file_load(env, backup)

    with pytest.raises(InvalidAdminInputError, match="email"):
        await store.resolve_declare("x'@example.org", "admin", ADMIN_PASSWORD)

    assert env.read_text(encoding="utf-8") == BASE_ENV


async def test_resolve_declare_concurrent_calls_declare_one_account(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)
    store = AdminAccountStore.file_load(env, backup)

    results = await asyncio.gather(
        store.resolve_declare("un@example.org", "premier", ADMIN_PASSWORD),
        store.resolve_declare("deux@example.org", "second", ADMIN_PASSWORD),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], EnvEntriesPresentError)
    entries = file_read_env(env)
    assert entries["MILES_ADMIN_USERNAME"] in {"premier", "second"}
    assert env.read_text(encoding="utf-8").count("MILES_ADMIN_USERNAME") == 1
