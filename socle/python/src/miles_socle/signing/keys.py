from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Ed25519, et non RSA ni ECDSA. Trois raisons, dans l'ordre où elles comptent :
#   — aucun paramètre à choisir : pas de mode de remplissage, pas de courbe, pas d'agilité
#     de hachage. Les pannes de signature les plus coûteuses viennent de ces choix, pas
#     de la primitive ;
#   — signature DÉTERMINISTE : rien d'aléatoire n'est tiré à la signature, donc aucun
#     risque de réutilisation de nonce — qui, en ECDSA, livre la clé privée ;
#   — clé publique de 32 octets : elle tient en 43 caractères, et l'appariement la fait
#     voyager dans une charge JSON et, un jour, sous les yeux d'un humain.
ALGORITHM = "ed25519"
_PUBLIC_KEY_BYTES = 32
# Empreinte tronquée à 16 octets : elle sert à NOMMER une clé dans un journal ou sur un
# écran, pas à la transporter. 32 caractères hexadécimaux se comparent à l'œil, ce qu'une
# clé entière ne permet pas, et la collision n'a aucun intérêt pour un attaquant — la
# vérification porte toujours sur la clé entière, jamais sur l'empreinte.
_FINGERPRINT_BYTES = 16


class SigningKeyError(ValueError):
    """Clé absente, mal formée ou du mauvais type. Le message ne porte jamais de clé privée."""


@dataclass(frozen=True)
class KeyPair:
    """Une paire engendrée, telle qu'elle sera rangée : la privée en PEM, la publique en base64url.

    Deux formats, et c'est voulu. La clé privée est rangée en PKCS#8 PEM, SANS phrase de
    passe : le dispositif des secrets la chiffre déjà au repos (AES-GCM sous
    MILES_SECRETS_KEY), et une phrase de passe ne ferait que créer un second secret à
    ranger quelque part. La clé publique, elle, voyage — charge JSON de l'appariement,
    écran — d'où une forme courte et sans retour à la ligne.
    """

    private_pem: str
    public_key: str


def generate_keypair() -> KeyPair:
    """Engendre une paire chez soi. La clé privée ne sort jamais de cette valeur de retour."""
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return KeyPair(pem, encode_public_key(private.public_key()))


def load_private_key(pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeEncodeError):
        # Jamais le contenu dans le message : il est en train d'échouer, mais c'est
        # encore une clé privée.
        raise SigningKeyError("clé privée illisible") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError(f"clé privée d'un autre type que {ALGORITHM}")
    return key


def encode_public_key(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_public_key(encoded: str) -> Ed25519PublicKey:
    """Décode une clé publique reçue. Entrée venue du réseau : validée avant tout usage."""
    raw = _decode_public_bytes(encoded)
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        raise SigningKeyError("clé publique invalide") from None


def fingerprint(encoded: str) -> str:
    """Empreinte d'une clé publique, pour un journal ou un écran de diagnostic."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(_decode_public_bytes(encoded))
    return digest.finalize()[:_FINGERPRINT_BYTES].hex()


def _decode_public_bytes(encoded: str) -> bytes:
    # Le rembourrage « = » est optionnel à l'écriture : on le rétablit avant de décoder,
    # sinon une clé parfaitement valide est refusée selon qui l'a encodée.
    padded = encoded.strip() + "=" * (-len(encoded.strip()) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise SigningKeyError("clé publique n'est pas du base64 url-safe") from None
    if len(raw) != _PUBLIC_KEY_BYTES:
        raise SigningKeyError(f"clé publique {ALGORITHM} : {_PUBLIC_KEY_BYTES} octets attendus")
    return raw
