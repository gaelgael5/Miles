from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from miles.auth.admin_account import (
    ADMIN_EMAIL_KEY,
    ADMIN_KEYS,
    ADMIN_PASSWORD_HASH_KEY,
    ADMIN_USERNAME_KEY,
    AdminAccount,
    resolve_admin_account,
    validate_admin_identity,
)
from miles.auth.env_file import file_append_entries, file_read_env
from miles.auth.passwords import check_password_policy, hash_password

log = structlog.get_logger(__name__)


class AdminAccountStore:
    """Compte d'amorçage tel que l'écrit .env, seule source de vérité.

    Le compte est relu dans le fichier monté, et non dans l'environnement du
    processus : après l'amorçage, il est actif sans redémarrage (choix laissé au
    ticket, retenu pour que l'utilisateur arrive connecté sur le portail).
    """

    def __init__(self, env_path: Path, backup_path: Path, account: AdminAccount | None) -> None:
        self._env_path = env_path
        self._backup_path = backup_path
        self._account = account

    @classmethod
    def file_load(cls, env_path: Path, backup_path: Path) -> AdminAccountStore:
        # Au démarrage, hors boucle asynchrone : une erreur ici doit empêcher le
        # service de démarrer plutôt que d'ouvrir l'amorçage par défaut.
        return cls(env_path, backup_path, resolve_admin_account(file_read_env(env_path)))

    @property
    def account(self) -> AdminAccount | None:
        return self._account

    async def resolve_declare(self, email: str, username: str, password: str) -> AdminAccount:
        validate_admin_identity(email, username)
        check_password_policy(password)
        # Hachage et écriture hors de la boucle : argon2id coûte volontairement cher.
        password_hash = await asyncio.to_thread(hash_password, password)
        entries = {
            ADMIN_EMAIL_KEY: email,
            ADMIN_USERNAME_KEY: username,
            ADMIN_PASSWORD_HASH_KEY: password_hash,
        }
        await asyncio.to_thread(
            file_append_entries, self._env_path, self._backup_path, entries, ADMIN_KEYS
        )
        # Relu dans le fichier plutôt que construit en mémoire : on sert ce qui est
        # réellement écrit, et une écriture tronquée se verrait ici.
        account = resolve_admin_account(await asyncio.to_thread(file_read_env, self._env_path))
        if account is None:
            raise RuntimeError("compte d'amorçage absent de .env juste après son écriture")
        self._account = account
        log.info("amorcage_effectue", username=account.username, email=account.email)
        return account
