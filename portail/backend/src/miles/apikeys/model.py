from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# La MÉCANIQUE de la clé est au socle depuis le 02/11/2026 (deuxième usage : le module
# d'environnement en émet pour ses points d'entrée d'ingestion). Elle est importée, pas
# recopiée : une divergence du hachage, de la comparaison en temps constant ou du préfixe
# affiché serait un défaut de sécurité qu'aucun test ne signalerait de part et d'autre.
from miles_socle.apikeys.model import (
    KEY_BYTES,
    KEY_DIRECTORY,
    KEY_ID_RE,
    KEY_PREFIX,
    KEY_RE,
    LAST_USED_GRANULARITY,
    SHOWN_LENGTH,
    key_digest,
    new_key,
    same_digest,
    shown_prefix,
)

# Réexportés sous leur nom d'origine : les appelants du portail n'ont pas à savoir que la
# mécanique a déménagé, et `ruff` ne prend pas ces imports pour des oublis.
__all__ = [
    "KEY_BYTES",
    "KEY_DIRECTORY",
    "KEY_ID_RE",
    "KEY_PREFIX",
    "KEY_RE",
    "LAST_USED_GRANULARITY",
    "SHOWN_LENGTH",
    "Access",
    "ApiKeyInfo",
    "Grant",
    "KeyPrincipal",
    "key_digest",
    "new_key",
    "same_digest",
    "shown_prefix",
]


class Access(StrEnum):
    READ = "lecture"
    WRITE = "ecriture"


@dataclass(frozen=True)
class Grant:
    """Ce qu'une clé du PORTAIL ouvre : un workspace, avec un niveau d'accès.

    Reste au produit, et c'est délibéré : le module d'environnement octroie une SOURCE
    d'ingestion, sans niveau d'accès — une clé d'ingestion écrit, c'est tout ce qu'elle
    fait. Réunir les deux derrière une abstraction obligerait chaque produit à porter la
    notion de l'autre.
    """

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
    # « api_key » : une clé de service ; « oauth » : une autorisation consentie à un client
    # OAuth (story 9f09cd8b), dont key_id est alors l'identifiant d'autorisation.
    kind: str = "api_key"

    def access_to(self, workspace_id: str) -> Access | None:
        for grant in self.grants:
            if grant.workspace_id == workspace_id:
                return grant.access
        return None

    def can_read(self, workspace_id: str) -> bool:
        return self.access_to(workspace_id) is not None

    def can_write(self, workspace_id: str) -> bool:
        return self.access_to(workspace_id) is Access.WRITE
