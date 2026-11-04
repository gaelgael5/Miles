from __future__ import annotations

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# argon2id avec les paramètres par défaut d'argon2-cffi (profil RFC 9106 « faible
# mémoire ») : un hachage rapide, même salé, se casse hors ligne à grande vitesse.
_HASHER = PasswordHasher()
ARGON2ID_PREFIX = "$argon2id$"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


class WeakPasswordError(ValueError):
    """Le mot de passe ne respecte pas la politique.

    La règle est un code et sa limite, pas une phrase : l'IHM la traduit dans la
    culture du visiteur.
    """

    def __init__(self, rule: str, limit: int, text: str) -> None:
        super().__init__(text)
        self.rule = rule
        self.limit = limit


def check_password_policy(password: str) -> None:
    # Longueur seule : les règles de composition poussent vers des mots de passe
    # courts et prévisibles. Le plafond borne le coût d'un hachage soumis par un inconnu.
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            "min_length", MIN_PASSWORD_LENGTH, f"au moins {MIN_PASSWORD_LENGTH} caractères"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            "max_length", MAX_PASSWORD_LENGTH, f"au plus {MAX_PASSWORD_LENGTH} caractères"
        )


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def is_argon2id_hash(candidate: str) -> bool:
    if not candidate.startswith(ARGON2ID_PREFIX):
        return False
    try:
        extract_parameters(candidate)
    except InvalidHashError:
        return False
    return True


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False
