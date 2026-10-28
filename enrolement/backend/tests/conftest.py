from __future__ import annotations

import pytest
from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.passwords import hash_password
from miles_socle.testing import DSN, SECRETS_KEY
from miles_socle.testing.fixtures import env_files
from pydantic import SecretStr

from enrolement.config import Settings

# `env_files` vient du socle : les trois produits montaient le même `.env` d'essai. Importée
# et non redéfinie — l'import suffit à pytest pour l'enregistrer —, d'où le réexport.
__all__ = ["DSN", "SECRETS_KEY", "env_files"]


@pytest.fixture
def settings(env_files: tuple[object, object]) -> Settings:
    """La configuration du produit : c'est SA classe, et elle reste chez lui."""
    env, backup = env_files
    return Settings(  # type: ignore[arg-type]
        database_url=DSN,
        env_file=env,
        env_backup_file=backup,
        secrets_key=SECRETS_KEY,
    )


@pytest.fixture
def admin_account() -> AdminAccount:
    """Le compte d'amorçage du produit : son adresse le nomme, elle ne se partage pas."""
    return AdminAccount(
        email="admin@enrolement.invalid",
        username="admin",
        password_hash=SecretStr(hash_password("mot-de-passe-d-essai-suffisant")),
    )
