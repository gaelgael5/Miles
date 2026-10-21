from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miles.git.forge import Repository
from miles.git.rights import Reason, classify
from miles.git.runner import GitResult, run_git
from miles.secrets.model import Secret

WORK_BRANCH_PREFIX = "work/"
WORK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MANIFEST = "manifest.json"
# Contenu initial du manifeste. Le plancher de version reste un point ouvert du cadrage
# (« déclaration du plancher de version ») : null dit « aucun », sans en inventer un.
INITIAL_MANIFEST: dict[str, Any] = {
    "format_version": 1,
    "min_app_version": None,
    "capabilities": [],
}

# Arborescence retenue au cadrage (« Back-office — capacités attendues »). Elle porte
# le métier par domaine et le transverse à la racine — et aucun dossier d'environnement.
_SHARED = {"messages", "components", "referentials", "theme"}
_DOMAIN = {"messages", "mappings", "referentials", "components", "screens", "scenarios"}
_MAPPINGS = {"inbound", "outbound"}
SKELETON = (
    "contracts",
    *(f"shared/{d}" for d in sorted(_SHARED)),
    "domains",
)
# Fichiers que poussent les forges ou les outils à la création d'un dépôt : un dépôt qui
# n'a qu'eux est vierge, pas « non conforme ».
_TOLERATED_ROOT = {"README", "README.md", "LICENSE", "LICENSE.md", ".gitignore", ".gitattributes"}
# Noms qui trahissent un dossier par environnement : l'environnement est une branche.
_ENVIRONMENT_NAMES = re.compile(
    r"^(env|envs|environments?|environnements?|prod.*|preprod.*|recette.*|staging|dev|test|qa)$",
    re.I,
)


class WorkBranchError(Exception):
    """Refus ; rien n'a été écrit dans le dépôt."""


class RepositoryAccessError(WorkBranchError):
    def __init__(self, reason: Reason) -> None:
        super().__init__(f"dépôt inaccessible : {reason.value}")
        self.reason = reason


class BranchExistsError(WorkBranchError):
    pass


@dataclass
class TreeDiagnosis:
    unexpected: list[str] = field(default_factory=list)
    environment_dirs: list[str] = field(default_factory=list)
    manifest: str = "absent"  # absent | invalide | valide

    @property
    def conform(self) -> bool:
        return not self.unexpected and not self.environment_dirs and self.manifest == "valide"


class NonConformTreeError(WorkBranchError):
    """Arborescence non conforme : on ne modifie rien et on dit pourquoi (critère 5)."""

    def __init__(self, diagnosis: TreeDiagnosis) -> None:
        super().__init__("arborescence non conforme")
        self.diagnosis = diagnosis


@dataclass(frozen=True)
class WorkBranch:
    branch: str
    # « initialisee » : un commit a posé l'ossature ; « conforme » : rien n'a été écrit.
    outcome: str


def work_branch_name(name: str) -> str:
    if not WORK_NAME_RE.match(name):
        raise ValueError("nom de branche de travail invalide")
    return WORK_BRANCH_PREFIX + name


def diagnose(paths: list[str], manifest_text: str | None) -> TreeDiagnosis:
    """Compare les chemins du dépôt à l'arborescence retenue, sans rien écrire."""
    diagnosis = TreeDiagnosis(manifest=_manifest_state(manifest_text))
    for path in paths:
        parts = path.split("/")
        if _is_environment(parts):
            top = parts[0]
            if top not in diagnosis.environment_dirs:
                diagnosis.environment_dirs.append(top)
        elif not _allowed(parts):
            diagnosis.unexpected.append(path)
    return diagnosis


def is_blank(paths: list[str]) -> bool:
    return all(path in _TOLERATED_ROOT or path.startswith(".github/") for path in paths)


def _manifest_state(text: str | None) -> str:
    if text is None:
        return "absent"
    try:
        data = json.loads(text)
    except ValueError:
        return "invalide"
    valid = (
        isinstance(data, dict)
        and data.get("format_version") == 1
        and isinstance(data.get("capabilities"), list)
        and all(isinstance(c, str) for c in data["capabilities"])
        and (data.get("min_app_version") is None or isinstance(data["min_app_version"], str))
    )
    return "valide" if valid else "invalide"


def _is_environment(parts: list[str]) -> bool:
    return len(parts) > 1 and bool(_ENVIRONMENT_NAMES.match(parts[0]))


def _allowed(parts: list[str]) -> bool:
    top = parts[0]
    if len(parts) == 1:
        return top == MANIFEST or top in _TOLERATED_ROOT
    if top == ".github":
        return True
    if top == "contracts":
        return True
    if top == "shared":
        return parts[1] in _SHARED or parts[1] == ".gitkeep"
    if top == "domains":
        return _allowed_in_domain(parts[2:]) if len(parts) > 2 else True
    return False


def _allowed_in_domain(rest: list[str]) -> bool:
    if len(rest) <= 1:
        return not rest or rest[0] == ".gitkeep"
    if rest[0] not in _DOMAIN:
        return False
    if rest[0] == "mappings" and len(rest) > 2:
        return rest[1] in _MAPPINGS
    return True


async def open_work_branch(repo: Repository, token: Secret, name: str, author: str) -> WorkBranch:
    branch = work_branch_name(name)
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-work-"))
    try:
        return await _Opener(repo, token, workdir, branch, author).run()
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


@dataclass
class _Opener:
    repo: Repository
    token: Secret
    workdir: Path
    branch: str
    author: str

    async def git(self, *args: str, cwd: Path | None = None) -> GitResult:
        return await run_git(list(args), cwd or self.workdir, self.token)

    async def run(self) -> WorkBranch:
        heads = await self.git("ls-remote", "--symref", self.repo.url, "HEAD", "refs/heads/*")
        if not heads.ok:
            raise RepositoryAccessError(classify(heads))
        if f"refs/heads/{self.branch}" in heads.stdout:
            raise BranchExistsError(self.branch)
        default = _default_branch(heads.stdout)
        clone = self.workdir / "clone"
        if default is None:
            await self.git("init", "-q", "-b", self.branch, str(clone))
            paths: list[str] = []
        else:
            cloned = await self.git(
                "clone", "-q", "--depth", "1", "--branch", default, self.repo.url, str(clone)
            )
            if not cloned.ok:
                raise RepositoryAccessError(classify(cloned))
            listed = await self.git("ls-tree", "-r", "--name-only", "HEAD", cwd=clone)
            paths = [line for line in listed.stdout.splitlines() if line]
            await self.git("checkout", "-q", "-b", self.branch, cwd=clone)
        outcome = await self._prepare(clone, paths)
        pushed = await self.git(
            "push", "-q", self.repo.url, f"HEAD:refs/heads/{self.branch}", cwd=clone
        )
        if not pushed.ok:
            raise RepositoryAccessError(classify(pushed))
        return WorkBranch(self.branch, outcome)

    async def _prepare(self, clone: Path, paths: list[str]) -> str:
        if is_blank(paths):
            await asyncio.to_thread(_write_skeleton, clone)
            await self.git("add", "-A", cwd=clone)
            committed = await self.git(
                "commit",
                "-q",
                f"--author={self.author}",
                "-m",
                "Initialisation de l'arborescence de paramétrage",
                cwd=clone,
            )
            if not committed.ok:
                raise RepositoryAccessError(Reason.FAILED)
            return "initialisee"
        manifest = await asyncio.to_thread(_read_text, clone / MANIFEST)
        diagnosis = diagnose(paths, manifest)
        if not diagnosis.conform:
            # Jamais d'écriture optimiste sur une arborescence qu'on ne reconnaît pas.
            raise NonConformTreeError(diagnosis)
        return "conforme"


def _default_branch(ls_remote: str) -> str | None:
    """Branche par défaut annoncée par la forge ; à défaut main, puis la première listée.

    Jamais « aucune » quand des branches existent : ce serait traiter comme vierge un
    dépôt qui a du contenu, et y écrire une ossature sans l'avoir diagnostiqué.
    """
    heads: list[str] = []
    for line in ls_remote.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line.removeprefix("ref: refs/heads/").split("\t", 1)[0]
        ref = line.split("\t", 1)[-1]
        if ref.startswith("refs/heads/"):
            heads.append(ref.removeprefix("refs/heads/"))
    if "main" in heads:
        return "main"
    return sorted(heads)[0] if heads else None


def _write_skeleton(root: Path) -> None:
    for directory in SKELETON:
        target = root / directory
        target.mkdir(parents=True, exist_ok=True)
        # git ne versionne pas un dossier vide : un marqueur garde l'ossature visible.
        (target / ".gitkeep").write_text("", encoding="utf-8")
    (root / MANIFEST).write_text(json.dumps(INITIAL_MANIFEST, indent=2) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def diagnosis_json(diagnosis: TreeDiagnosis) -> dict[str, Any]:
    return {
        "unexpected": diagnosis.unexpected,
        "environment_dirs": diagnosis.environment_dirs,
        "manifest": diagnosis.manifest,
    }
