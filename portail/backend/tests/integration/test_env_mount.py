from __future__ import annotations

import os
from pathlib import Path

import pytest

from miles.auth.admin_store import AdminAccountStore
from miles.auth.env_file import file_read_env

pytestmark = pytest.mark.integration

PASSWORD = "phrase de passe du test de montage"


def _mounted(variable: str) -> Path:
    # Posé par scripts/run-integration-tests.sh, qui monte ces fichiers UN PAR UN,
    # comme docker-compose.yml : c'est ce montage-là qu'on éprouve, pas un dossier.
    value = os.environ.get(variable)
    if not value:
        pytest.fail(f"{variable} absent : lancer via scripts/run-integration-tests.sh")
    return Path(value)


async def test_bootstrap_writes_through_single_file_mounts() -> None:
    env, backup = _mounted("MILES_TEST_MOUNTED_ENV"), _mounted("MILES_TEST_MOUNTED_BAK")
    original = env.read_bytes()
    store = AdminAccountStore.file_load(env, backup)
    assert store.account is None

    account = await store.resolve_declare("gael@example.org", "admin", PASSWORD)

    # Le script relit ensuite les fichiers CÔTÉ HÔTE : c'est là que l'écriture compte.
    assert env.read_bytes().startswith(original)
    assert backup.read_bytes() == original
    assert file_read_env(env)["MILES_ADMIN_USERNAME"] == account.username
    assert PASSWORD not in env.read_text(encoding="utf-8")
