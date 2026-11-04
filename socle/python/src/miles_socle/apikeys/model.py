"""La clé elle-même : comment on la fabrique, ce qu'on en garde, comment on la compare."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

# Préfixe lisible : une clé qui fuit dans un journal ou un dépôt se reconnaît d'un coup
# d'œil, et les scanners de secrets peuvent la chercher.
KEY_PREFIX = "mlk_"
# 32 octets du hasard (256 bits), en base64 url sans remplissage : 43 caractères.
KEY_BYTES = 32
KEY_RE = re.compile(r"^mlk_[A-Za-z0-9_-]{43}$")
# Préfixe affiché : le préfixe lisible et 8 caractères, assez pour reconnaître une clé
# dans la liste, très loin d'assez pour la deviner.
SHOWN_LENGTH = len(KEY_PREFIX) + 8
KEY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Annuaire des auteurs-clés : une clé n'est pas une personne, le journal le dit.
KEY_DIRECTORY = "apikey"
# Le dernier usage se tient à la minute près : l'écrire à chaque appel ferait de chaque
# appel une écriture en base, pour une information qui ne sert qu'à l'inventaire — et
# sur un point d'entrée d'ingestion, ce serait une écriture par dépôt.
LAST_USED_GRANULARITY = timedelta(minutes=1)


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(KEY_BYTES)


def key_digest(raw: str) -> bytes:
    """Empreinte SHA-256 de la clé entière : la seule trace qu'on garde.

    Pas de hachage lent : la clé tire 256 bits du hasard, elle n'est pas devinable par
    force brute, et un KDF n'ajouterait qu'un coût par appel sur un chemin chaud.
    """
    return hashlib.sha256(raw.encode()).digest()


def shown_prefix(raw: str) -> str:
    return raw[:SHOWN_LENGTH]


def same_digest(left: bytes, right: bytes) -> bool:
    # Temps constant : la recherche se fait par l'empreinte, mais on ne laisse pas une
    # comparaison courte dire combien d'octets concordent.
    return hmac.compare_digest(left, right)
