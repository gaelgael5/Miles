from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from miles_socle.events.catalog import EventShape, closed_block
from miles_socle.events.model import DelegatedAuthor, EventAuthor

from miles.git.rights import AccessReport

CREATED_EVENT = "workspace.created"
CHECKED_EVENT = "workspace.access_checked"
WORK_BRANCH_EVENT = "workspace.work_branch_opened"
REPOSITORY_EVENT = "workspace.repository_set"
SECURITY_SERVICE_EVENT = "workspace.security_service_set"
DELETED_EVENT = "workspace.deleted"
# --- Les formes, mesurées sur `workspaces/service.py` et `gitaccess/dependents.py` ----
# `workspace.access_checked` a DEUX producteurs — la vérification d'un workspace et celle
# que déclenche la modification d'une connexion git —, et tous deux passent par
# `check_summary` ci-dessous. Une seule forme, donc, et c'est ce qui le garantit.
_URL: dict[str, object] = {"type": "string", "minLength": 1}
EVENT_SHAPES = (
    EventShape(
        CREATED_EVENT,
        "Workspace créé",
        closed_block({"name": {"type": "string", "minLength": 1}, "default_culture": _URL}),
    ),
    EventShape(
        CHECKED_EVENT,
        "Droits sur le dépôt vérifiés",
        # Les cinq droits par leur nom, chacun avec « ok » ou la raison du refus : c'est
        # ce qu'on relit quand un push échoue, et une liste de booléens n'y répondrait
        # pas. Les résidus sont NULS quand l'essai a tout retiré — ce qu'il n'a pas pu
        # retirer est à supprimer à la main, et n'est jamais oublié en silence.
        closed_block(
            {
                "repo_url": _URL,
                "branch": {"type": "string", "minLength": 1},
                "all_passed": {"type": "boolean"},
                "checks": {"type": "object", "additionalProperties": {"type": "string"}},
                "residual_branch": {"type": ["string", "null"]},
                "residual_tag": {"type": ["string", "null"]},
            }
        ),
    ),
    EventShape(
        WORK_BRANCH_EVENT,
        "Branche de travail ouverte",
        # `outcome` dit ce que l'ouverture a VRAIMENT fait — créée, déjà là, dépôt
        # initialisé : un geste idempotent doit dire laquelle des trois issues il a prise.
        closed_block({"branch": {"type": "string", "minLength": 1}, "outcome": _URL}),
    ),
    EventShape(
        REPOSITORY_EVENT,
        "Dépôt du workspace enregistré",
        closed_block({"repo_url": _URL, "git_connection_id": _URL}),
    ),
    EventShape(
        SECURITY_SERVICE_EVENT,
        "Service de sécurité du workspace changé",
        # NUL quand on le détache, et non absent : « depuis quand ce workspace n'a-t-il
        # plus de service de sécurité ? » doit se lire sans interpréter une absence.
        closed_block({"security_service_id": {"type": ["string", "null"]}}),
    ),
    EventShape(
        DELETED_EVENT,
        "Workspace supprimé",
        # Le dépôt est NUL pour un workspace qui n'en avait jamais reçu. Les deux champs
        # sont la seule trace de ce que la ligne portait.
        closed_block(
            {"name": {"type": "string", "minLength": 1}, "repo_url": {"type": ["string", "null"]}}
        ),
    ),
)
# DÉRIVÉ des formes, jamais recopié : deux listes auraient divergé au premier type ajouté.
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
NAME_MAX = 200
SELECT = (
    "SELECT w.id, w.name, w.repo_url, w.git_connection_id, w.security_service_id,"
    " w.last_check, w.last_check_at, w.created_at, w.updated_at, b.branch AS work_branch"
    " FROM workspaces w"
    " LEFT JOIN workspace_work_branches b ON b.workspace_id = w.id"
)
_COMMIT_IDENTITY_RE = re.compile(r"[^A-Za-z0-9._-]")
# Ce qu'un nom ou un e-mail lu ailleurs (forge, portail) ne peut pas porter dans un auteur git.
_UNSAFE_IDENTITY_RE = re.compile(r"[<>\x00-\x1f\x7f]")


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


class BranchNotFoundError(WorkspaceNotFoundError):
    """Slug de branche inconnu du workspace : ni la base, ni une branche fille déclarée.

    Fille de WorkspaceNotFoundError pour que tout point d'entrée de l'atelier la refuse
    déjà ; chacun la nomme avant le cas général, sinon elle se lirait « workspace inconnu ».
    """


class WorkspaceHeldError(WorkspaceConflictError):
    """Suppression retenue : quelqu'un a la main sur une branche du workspace.

    Les prises de main portent du travail local non publié ; les laisser tomber en
    cascade le perdrait sans rien dire. On nomme le porteur pour qu'il puisse publier
    ou relâcher (ou l'administrateur déverrouiller, ce qui range le travail).
    """

    def __init__(self, holder: str) -> None:
        super().__init__("branche_tenue")
        self.holder = holder


class HoldRequiredError(WorkspaceConflictError):
    """Modifier une branche fille suppose d'en avoir la main (story 9def0adc, critère 5).

    `holder` : qui la tient, pour que le refus le nomme ; None si personne.
    """

    def __init__(self, holder: str | None) -> None:
        super().__init__("prise_de_main_requise")
        self.holder = holder


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
    # Absents tant que le dépôt n'est pas paramétré : un workspace se crée par son seul
    # nom (21/10/2026), et les deux vont ensemble (contrainte de la table).
    repo_url: str | None
    git_connection_id: str | None
    security_service_id: str | None
    last_check: dict[str, Any] | None
    last_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Aucune à la création : elle s'ouvre quand on commence à travailler (e2719a5c).
    work_branch: str | None = None


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
    if isinstance(author, DelegatedAuthor):
        # Par MCP : la personne signée par le portail (ou la clé seule), résolue à l'appel.
        return author.commit_identity
    subject = _COMMIT_IDENTITY_RE.sub("-", author.subject)[:60] or "inconnu"
    directory = _COMMIT_IDENTITY_RE.sub("-", author.directory)[:60] or "inconnu"
    return f"{subject} via Miles <{subject}@{directory}.miles.invalid>"


def git_signature(name: str, email: str) -> str:
    """« Nom <e-mail> » sûr pour git, depuis des valeurs lues hors de Miles."""
    return f"{_clean_identity(name)} <{_clean_identity(email)}>"


def _clean_identity(text: str) -> str:
    return _UNSAFE_IDENTITY_RE.sub("", text).strip()[:100] or "inconnu"


MAX_LABEL = 120


def checked_label(label: str) -> str:
    """Label saisi d'un objet du workspace (contrat, branche) : une ligne lisible."""
    label = label.strip()
    if not label:
        raise WorkspaceInputError("label", "vide")
    # Caractères de contrôle refusés : le label s'affiche dans le menu et les journaux, où
    # un retour à la ligne ou une séquence d'échappement fausserait la lecture.
    if len(label) > MAX_LABEL or any(unicodedata.category(c) == "Cc" for c in label):
        raise WorkspaceInputError("label")
    return label
