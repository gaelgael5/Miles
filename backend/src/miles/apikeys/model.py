from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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


class Access(StrEnum):
    READ = "lecture"
    WRITE = "ecriture"


@dataclass(frozen=True)
class Grant:
    workspace_id: str
    access: Access


@dataclass(frozen=True)
class ApiKeyInfo:
    """Ce qui se montre d'une clé : jamais la clé elle-même."""

    id: str
    label: str
    prefix: str
    grants: tuple[Grant, ...]
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True)
class KeyPrincipal:
    """L'appelant d'une requête MCP : la clé, et ses droits lus à l'instant de l'appel."""

    key_id: str
    label: str
    grants: tuple[Grant, ...]

    def access_to(self, workspace_id: str) -> Access | None:
        for grant in self.grants:
            if grant.workspace_id == workspace_id:
                return grant.access
        return None

    def can_read(self, workspace_id: str) -> bool:
        return self.access_to(workspace_id) is not None

    def can_write(self, workspace_id: str) -> bool:
        return self.access_to(workspace_id) is Access.WRITE


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(KEY_BYTES)


def key_digest(raw: str) -> bytes:
    return hashlib.sha256(raw.encode()).digest()


def shown_prefix(raw: str) -> str:
    return raw[:SHOWN_LENGTH]


def same_digest(left: bytes, right: bytes) -> bool:
    # Temps constant (critère 11) : la recherche se fait par l'empreinte, mais on ne
    # laisse pas une comparaison courte dire combien d'octets concordent.
    return hmac.compare_digest(left, right)
