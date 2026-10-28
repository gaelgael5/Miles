from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.passwords import hash_password
from pydantic import SecretStr

from environnement.config import Settings

DSN = "postgresql://miles:x@db:5432/miles"
# Clé de 32 octets en base64url, comme celle que dev-deploy.sh engendre. Valeur d'essai
# sans portée hors des tests : aucun secret du dépôt ne passe par là.
SECRETS_KEY = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaQ"


@pytest.fixture
def env_files(tmp_path: Path) -> tuple[Path, Path]:
    """Le .env de l'hôte et sa sauvegarde, que le produit monte fichier par fichier."""
    env, backup = tmp_path / ".env", tmp_path / ".env.bak"
    env.write_text("", encoding="utf-8")
    backup.write_text("", encoding="utf-8")
    return env, backup


@pytest.fixture
def settings(env_files: tuple[Path, Path]) -> Settings:
    env, backup = env_files
    return Settings(  # type: ignore[arg-type]
        database_url=DSN,
        env_file=env,
        env_backup_file=backup,
        secrets_key=SECRETS_KEY,
    )


@pytest.fixture
def admin_account() -> AdminAccount:
    return AdminAccount(
        email="admin@environnement.invalid",
        username="admin",
        password_hash=SecretStr(hash_password("mot-de-passe-d-essai-suffisant")),
    )
