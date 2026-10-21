from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from miles.git.rights import AccessReport

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
LABEL_MAX = 200
CERT_PEM_MAX = 16384
TOKEN_TYPE = "GIT_TOKEN"  # noqa: S105  # nom du type, pas une valeur
CLIENT_KEY_TYPE = "GIT_CLIENT_KEY"

CERTIFICATE_CREATED = "client_certificate.created"
CERTIFICATE_REPLACED = "client_certificate.replaced"
CERTIFICATE_DELETED = "client_certificate.deleted"
CONNECTION_CREATED = "git_connection.created"
CONNECTION_UPDATED = "git_connection.updated"
CONNECTION_DELETED = "git_connection.deleted"
EVENT_TYPES = frozenset(
    {
        CERTIFICATE_CREATED,
        CERTIFICATE_REPLACED,
        CERTIFICATE_DELETED,
        CONNECTION_CREATED,
        CONNECTION_UPDATED,
        CONNECTION_DELETED,
    }
)


class GitAccessError(Exception):
    """Refus ; le message ne porte jamais de secret."""


class GitAccessInputError(GitAccessError):
    def __init__(self, field: str, reason: str | None = None) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field, self.reason = field, reason


class GitAccessConflictError(GitAccessError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GitAccessNotFoundError(GitAccessError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class GitAccessInUseError(GitAccessError):
    """Encore utilisé : on nomme qui s'en sert, pour que l'administrateur sache quoi détacher."""

    def __init__(self, users: tuple[str, ...]) -> None:
        super().__init__(f"utilisé par {len(users)} objet(s)")
        self.users = users


class DependentCheckFailedError(GitAccessError):
    """Un workspace perdrait un des cinq droits : rien n'est appliqué (décision du 18/10/2026)."""

    def __init__(self, workspace_id: str, report: AccessReport) -> None:
        super().__init__(f"accès insuffisant pour le workspace {workspace_id}")
        self.workspace_id, self.report = workspace_id, report


class DependentOutsideError(GitAccessError):
    """La nouvelle adresse d'une connexion ne contiendrait plus le dépôt d'un workspace."""

    def __init__(self, workspace_id: str) -> None:
        super().__init__(f"dépôt du workspace {workspace_id} hors de l'adresse")
        self.workspace_id = workspace_id


@dataclass(frozen=True)
class CertificateRef:
    """Certificat public et désignation de sa clé privée, secret du socle."""

    cert_pem: str
    key_secret_slug: str


@dataclass(frozen=True)
class ClientCertificateRecord:
    id: str
    label: str
    cert_pem: str
    key_secret_slug: str
    not_after: datetime
    created_at: datetime
    updated_at: datetime
    # Connexions qui s'en servent : affichées, et motif du refus de suppression.
    connections: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitConnection:
    id: str
    label: str
    base_url: str
    # PAT, certificat, ou les deux ; jamais aucun (contrainte de la table).
    token_secret_slug: str | None
    certificate_id: str | None
    created_at: datetime
    updated_at: datetime
    workspaces: tuple[str, ...] = ()


def validate_id(value: str) -> str:
    if not ID_RE.match(value):
        raise GitAccessInputError("id")
    return value


def validate_label(value: str) -> str:
    label = value.strip()
    if not label or len(label) > LABEL_MAX:
        raise GitAccessInputError("label")
    return label
