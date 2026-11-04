from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from miles.git.rights import AccessReport

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
LABEL_MAX = 200
TOKEN_TYPE = "GIT_TOKEN"  # noqa: S105  # nom du type, pas une valeur

CONNECTION_CREATED = "git_connection.created"
CONNECTION_UPDATED = "git_connection.updated"
CONNECTION_DELETED = "git_connection.deleted"
EVENT_TYPES = frozenset({CONNECTION_CREATED, CONNECTION_UPDATED, CONNECTION_DELETED})


class GitAccessError(Exception):
    """Refus ; le message ne porte jamais de secret."""


class GitAccessInputError(GitAccessError):
    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


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
class GitConnection:
    id: str
    label: str
    base_url: str
    token_secret_slug: str
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
