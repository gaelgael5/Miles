from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import SecretStr

from miles.auth.passwords import is_argon2id_hash

ADMIN_EMAIL_KEY = "MILES_ADMIN_EMAIL"
ADMIN_USERNAME_KEY = "MILES_ADMIN_USERNAME"
ADMIN_PASSWORD_HASH_KEY = "MILES_ADMIN_PASSWORD_HASH"  # noqa: S105  # nom de clef, pas une valeur
ADMIN_KEYS = (ADMIN_EMAIL_KEY, ADMIN_USERNAME_KEY, ADMIN_PASSWORD_HASH_KEY)

# Pas d'apostrophe ni d'espace : la valeur est écrite entre apostrophes dans .env.
EMAIL_RE = re.compile(r"^[^@\s'\"]{1,64}@[^@\s'\"]{1,189}\.[^@\s'\"]{2,63}$")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class AdminConfigError(Exception):
    """Le compte d'amorçage de .env est incomplet ou invalide : on refuse de démarrer."""


class InvalidAdminInputError(ValueError):
    """Identité saisie à l'amorçage refusée ; le message nomme le champ."""


@dataclass(frozen=True)
class AdminAccount:
    email: str
    username: str
    password_hash: SecretStr


def validate_admin_identity(email: str, username: str) -> None:
    if not EMAIL_RE.match(email):
        raise InvalidAdminInputError("email")
    if not USERNAME_RE.match(username):
        raise InvalidAdminInputError("username")


def resolve_admin_account(entries: Mapping[str, str]) -> AdminAccount | None:
    """Compte déclaré, ou None s'il n'y en a aucun (l'amorçage est alors ouvert)."""
    present = [key for key in ADMIN_KEYS if entries.get(key)]
    if not present:
        return None
    if len(present) != len(ADMIN_KEYS):
        # Fail closed : un compte partiel vient d'une écriture interrompue ou d'une
        # retouche manuelle. Rouvrir l'amorçage ferait administrateur le premier venu.
        missing = sorted(set(ADMIN_KEYS) - set(present))
        raise AdminConfigError(
            f"compte d'amorçage incomplet dans .env ({', '.join(missing)} absent) : "
            "restaurer depuis .env.bak ou retirer les trois entrées MILES_ADMIN_*"
        )
    email, username, password_hash = (entries[key] for key in ADMIN_KEYS)
    try:
        validate_admin_identity(email, username)
    except InvalidAdminInputError as exc:
        raise AdminConfigError(f"MILES_ADMIN_{str(exc).upper()} invalide dans .env") from exc
    if not is_argon2id_hash(password_hash):
        # On nomme l'entrée, jamais sa valeur.
        raise AdminConfigError(f"{ADMIN_PASSWORD_HASH_KEY} n'est pas une empreinte argon2id")
    return AdminAccount(email=email, username=username, password_hash=SecretStr(password_hash))
