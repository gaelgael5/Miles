from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from miles.events.model import EventAuthor
from miles.git.rights import AccessReport

CREATED_EVENT = "workspace.created"
CHECKED_EVENT = "workspace.access_checked"
WORK_BRANCH_EVENT = "workspace.work_branch_opened"
CERTIFICATE_EVENT = "workspace.client_certificate_replaced"
EVENT_TYPES = frozenset({CREATED_EVENT, CHECKED_EVENT, WORK_BRANCH_EVENT, CERTIFICATE_EVENT})
NAME_MAX = 200
SELECT = (
    "SELECT w.id, w.name, w.repo_url, w.git_secret_slug, w.client_key_secret_slug,"
    " w.client_cert_pem, w.client_cert_not_after, w.security_service_id, w.last_check,"
    " w.last_check_at, w.created_at, w.updated_at, b.branch AS work_branch FROM workspaces w"
    " LEFT JOIN workspace_work_branches b ON b.workspace_id = w.id"
)
_COMMIT_IDENTITY_RE = re.compile(r"[^A-Za-z0-9._-]")


class WorkspaceError(Exception):
    """Refus ; le message ne porte jamais de secret."""


class WorkspaceInputError(WorkspaceError):
    def __init__(self, field: str, reason: str | None = None) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field, self.reason = field, reason


class WorkspaceConflictError(WorkspaceError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkspaceNotFoundError(WorkspaceError):
    pass


class RepositoryUnavailableError(WorkspaceError):
    """Le dépôt a cessé de répondre ou de nous laisser faire : on désigne l'accès (critère 10)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccessCheckFailedError(WorkspaceError):
    """Un des cinq droits manque : rien n'est enregistré (décision du 18/10/2026)."""

    def __init__(self, report: AccessReport) -> None:
        super().__init__("accès au dépôt insuffisant")
        self.report = report


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    repo_url: str
    # Jeton, certificat, ou les deux ; jamais aucun (contrainte de la table).
    git_secret_slug: str | None
    client_key_secret_slug: str | None
    client_cert_pem: str | None
    client_cert_not_after: datetime | None
    security_service_id: str | None
    last_check: dict[str, Any] | None
    last_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Aucune à la création : elle s'ouvre quand on commence à travailler (e2719a5c).
    work_branch: str | None = None


@dataclass(frozen=True)
class CertificateInput:
    cert_pem: str
    key_secret_slug: str


@dataclass(frozen=True)
class WorkspaceInput:
    id: str
    name: str
    repo_url: str
    git_secret_slug: str | None
    security_service_id: str | None
    certificate: CertificateInput | None = None


def workspace_from_row(row: Any) -> Workspace:
    data = dict(row)
    raw = data["last_check"]
    data["last_check"] = json.loads(raw) if isinstance(raw, str) else raw
    return Workspace(**data)


def report_json(report: AccessReport) -> dict[str, Any]:
    return asdict(report) | {"all_passed": report.all_passed}


def check_summary(repo_url: str, report: AccessReport) -> dict[str, Any]:
    return {
        "repo_url": repo_url,
        "branch": report.branch,
        "all_passed": report.all_passed,
        "checks": {c.right.value: c.reason.value if c.reason else "ok" for c in report.checks},
        "residual_branch": report.residual_branch,
        "residual_tag": report.residual_tag,
    }


def commit_author(author: EventAuthor) -> str:
    """Auteur du commit d'initialisation : la personne, et par où elle est entrée."""
    subject = _COMMIT_IDENTITY_RE.sub("-", author.subject)[:60] or "inconnu"
    directory = _COMMIT_IDENTITY_RE.sub("-", author.directory)[:60] or "inconnu"
    return f"{subject} via Miles <{subject}@{directory}.miles.invalid>"
