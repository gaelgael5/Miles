from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from miles.git.forge import Repository
from miles.git.runner import GitResult, run_git
from miles.secrets.model import Secret

VERIFICATION_PREFIX = "miles-verification-"
SUFFIX_RE = re.compile(r"^[0-9a-f]{8}$")


class Right(StrEnum):
    """Les cinq droits dont Miles se sert, dans l'ordre où l'essai les éprouve."""

    READ = "lire"
    CREATE_BRANCH = "creer_branche"
    PUSH = "pousser"
    TAG = "poser_tag"
    DELETE_BRANCH = "supprimer_branche"


class Reason(StrEnum):
    CREDENTIALS = "identifiants"
    REPOSITORY_NOT_FOUND = "depot_inexistant"
    UNREACHABLE = "injoignable"
    PROTECTED = "protection"
    FORBIDDEN = "droit_refuse"
    FAILED = "echec"


@dataclass(frozen=True)
class Check:
    right: Right
    ok: bool
    reason: Reason | None = None


@dataclass
class AccessReport:
    branch: str
    tag: str
    checks: list[Check] = field(default_factory=list)
    # Ce que l'essai n'a pas pu retirer : à supprimer à la main, et affiché tel quel
    # (critère 7). Jamais nettoyé ni oublié en silence.
    residual_branch: str | None = None
    residual_tag: str | None = None
    existing_branches: int = 0

    @property
    def all_passed(self) -> bool:
        return len(self.checks) == len(Right) and all(c.ok for c in self.checks)

    def failed(self) -> Check | None:
        return next((c for c in self.checks if not c.ok), None)


# Ordre significatif : une protection se lit aussi comme un refus d'écriture ; on la
# reconnaît d'abord, pour orienter vers la règle de protection (critère 13).
_REASONS: tuple[tuple[Reason, re.Pattern[str]], ...] = (
    (
        Reason.PROTECTED,
        re.compile(r"protected branch|GH006|GH013|pre-receive hook declined|rule viol", re.I),
    ),
    (Reason.REPOSITORY_NOT_FOUND, re.compile(r"repository not found|' not found", re.I)),
    (
        Reason.CREDENTIALS,
        re.compile(
            r"authentication failed|invalid username or password|could not read username"
            r"|returned error: 401",
            re.I,
        ),
    ),
    (
        Reason.FORBIDDEN,
        re.compile(r"permission to .* denied|write access|returned error: 403|denied", re.I),
    ),
    (
        Reason.UNREACHABLE,
        re.compile(
            r"could not resolve host|failed to connect|timed out|délai dépassé|unable to access",
            re.I,
        ),
    ),
)


def classify(result: GitResult) -> Reason:
    for reason, pattern in _REASONS:
        if pattern.search(result.stderr):
            return reason
    return Reason.FAILED


def verification_name(suffix: str) -> str:
    """Nom distinctif, improbable en collision ; le même sert à la branche et au tag."""
    if not SUFFIX_RE.match(suffix):
        raise ValueError("suffixe de vérification invalide")
    return f"{VERIFICATION_PREFIX}{suffix}"


async def run_access_check(repo: Repository, token: Secret, suffix: str) -> AccessReport:
    """Éprouve réellement les cinq droits, en écrivant (décision du 18/10/2026).

    Lire les permissions déclarées par la forge ne prouverait rien : une protection de
    branche ou une règle d'organisation fait refuser un push à un compte « autorisé ».
    """
    name = verification_name(suffix)
    report = AccessReport(name, name)
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-git-"))
    try:
        await _Probe(repo, token, workdir, report).run()
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)
    return report


@dataclass
class _Probe:
    repo: Repository
    token: Secret
    workdir: Path
    report: AccessReport

    async def git(self, *args: str) -> GitResult:
        return await run_git(list(args), self.workdir, self.token)

    def record(self, right: Right, result: GitResult) -> bool:
        reason = None if result.ok else classify(result)
        self.report.checks.append(Check(right, result.ok, reason))
        return result.ok

    async def run(self) -> None:
        listed = await self.git("ls-remote", "--heads", self.repo.url)
        if not self.record(Right.READ, listed):
            return
        self.report.existing_branches = len([line for line in listed.stdout.splitlines() if line])
        # Branche orpheline à commits vides : rien du contenu du dépôt n'est touché, et
        # un dépôt vide (cas nominal, critère 11) s'éprouve comme un autre.
        await self.git("init", "-q", "-b", self.report.branch)
        await self.git("commit", "-q", "--allow-empty", "-m", "Vérification des droits (1/2)")
        target = f"HEAD:refs/heads/{self.report.branch}"
        if not self.record(
            Right.CREATE_BRANCH, await self.git("push", "-q", self.repo.url, target)
        ):
            return
        await self.git("commit", "-q", "--allow-empty", "-m", "Vérification des droits (2/2)")
        if self.record(Right.PUSH, await self.git("push", "-q", self.repo.url, target)):
            await self._tag()
        await self._delete_branch()

    async def _tag(self) -> None:
        ref = f"refs/tags/{self.report.tag}"
        if not self.record(Right.TAG, await self.git("push", "-q", self.repo.url, f"HEAD:{ref}")):
            return
        removed = await self.git("push", "-q", self.repo.url, "--delete", ref)
        if not removed.ok:
            self.report.residual_tag = self.report.tag

    async def _delete_branch(self) -> None:
        # Tentée même après un push ou un tag refusé (critère 8) : la branche ne doit pas
        # rester. C'est aussi l'épreuve du cinquième droit quand tout le reste a passé.
        ref = f"refs/heads/{self.report.branch}"
        deleted = await self.git("push", "-q", self.repo.url, "--delete", ref)
        if not deleted.ok:
            self.report.residual_branch = self.report.branch
        if all(c.ok for c in self.report.checks) and len(self.report.checks) == len(Right) - 1:
            self.record(Right.DELETE_BRANCH, deleted)
