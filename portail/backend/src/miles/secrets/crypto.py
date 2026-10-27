from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from miles.secrets.model import Secret, SecretUndecipherableError

KEY_ENTRY = "MILES_SECRETS_KEY"
KEY_BYTES = 32
KEY_VERSION = 1
_NONCE_BYTES = 12
# Domaine propre à cet usage : la clé de .env ne chiffre jamais directement. Une
# clé dérivée par usage permet d'en ajouter d'autres sans réutiliser la même.
_HKDF_INFO = b"miles/secrets/v1"


class SecretsKeyError(ValueError):
    """Clé de chiffrement absente ou invalide. Le message ne contient jamais la clé."""


@dataclass(frozen=True)
class Sealed:
    key_version: int
    nonce: bytes
    ciphertext: bytes


def parse_secrets_key(raw: str) -> bytes:
    """Décode la clé de .env : base64 url-safe de 32 octets, sinon refus."""
    try:
        key = base64.b64decode(raw.strip(), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise SecretsKeyError(f"{KEY_ENTRY} n'est pas du base64 url-safe valide") from None
    if len(key) != KEY_BYTES:
        raise SecretsKeyError(f"{KEY_ENTRY} doit décoder {KEY_BYTES} octets")
    return key


class SecretCipher:
    """Chiffre et ouvre les valeurs de secrets.

    Limite assumée (décision du 20/10/2026) : la clé vit dans .env, sur la machine
    de la base. Le chiffrement protège une sauvegarde ou un export de la base, pas un
    accès root à la machine, qui lit les deux.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise SecretsKeyError(f"{KEY_ENTRY} doit décoder {KEY_BYTES} octets")
        derived = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=_HKDF_INFO)
        self._aead = AESGCM(derived.derive(key))

    def seal(self, slug: str, value: Secret) -> Sealed:
        # Nonce aléatoire à chaque chiffrement : réutiliser un nonce avec la même clé
        # casserait AES-GCM. Le slug en données associées lie le chiffré à sa ligne :
        # recopié sur un autre secret, il ne s'ouvre plus.
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, value.reveal().encode("utf-8"), slug.encode())
        return Sealed(KEY_VERSION, nonce, ciphertext)

    def open(self, slug: str, sealed: Sealed) -> Secret:
        if sealed.key_version != KEY_VERSION:
            raise SecretUndecipherableError(slug)
        try:
            plain = self._aead.decrypt(sealed.nonce, sealed.ciphertext, slug.encode())
        except InvalidTag:
            # Jamais de valeur approchée : une valeur corrompue servie à un fournisseur
            # ferait échouer l'appel loin de sa cause.
            raise SecretUndecipherableError(slug) from None
        return Secret(plain.decode("utf-8"))
