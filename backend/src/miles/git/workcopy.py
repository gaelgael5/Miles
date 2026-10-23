from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.rights import classify
from miles.git.runner import GitResult, run_git
from miles.git.worktree import RepositoryAccessError, WorkBranchError

_AUTHOR_RE = re.compile(r"^(?P<name>[^<>]+) <(?P<email>[^<>]+)>$")


def author_parts(author: str) -> tuple[str, str]:
    """(nom, e-mail) d'un auteur git « Nom <e-mail> » ; refus s'il est mal formé."""
    match = _AUTHOR_RE.match(author)
    if match is None:
        raise ValueError("auteur de commit mal formé")
    return match["name"], match["email"]


class BranchMissingError(WorkBranchError):
    """La branche n'existe pas sur la forge : on ne la recrée jamais implicitement."""


class BranchMovedError(WorkBranchError):
    """La branche a bougé pendant l'écriture : rien n'est poussé, l'appelant réessaie."""


@dataclass
class WorkCopy:
    """Copie locale jetable d'UNE branche, le temps d'un geste de lecture ou d'écriture.

    Rien n'est gardé entre deux gestes, ni en base ni en mémoire : git reste la seule
    source de vérité du paramétrage (cadrage, « Décisions d'architecture »).
    """

    repo: Repository
    access: GitAccess
    branch: str
    root: Path
    head: str = ""

    async def git(self, *args: str) -> GitResult:
        return await run_git(list(args), self.root, self.access)

    async def paths(self) -> list[str]:
        # Filtrés par l'appelant : dans un pathspec git, `*` traverse les `/`.
        listed = await self.git("ls-files", "-z")
        return sorted(p for p in listed.stdout.split("\0") if p)

    async def read(self, path: str) -> str | None:
        return await asyncio.to_thread(_read, self._inside(path))

    async def write(self, path: str, content: str) -> None:
        await asyncio.to_thread(_write, self._inside(path), content)

    async def remove(self, path: str) -> None:
        await self.git("rm", "-q", "--", path)

    async def commit_push(self, message: str, author: str) -> str:
        """Commit et push ; rend l'identifiant du commit. Refuse si la branche a bougé."""
        await self.git("add", "-A")
        committed = await self.git("commit", "-q", f"--author={author}", "-m", message)
        if not committed.ok:
            raise RepositoryAccessError(classify(committed))
        sha = (await self.git("rev-parse", "HEAD")).stdout.strip()
        ref = f"refs/heads/{self.branch}"
        # Bail sur la tête lue au départ : si la branche a été supprimée ou a avancé
        # entre-temps, le push échoue au lieu de la recréer ou d'écraser l'autre écriture.
        pushed = await self.git(
            "push", "-q", f"--force-with-lease={ref}:{self.head}", self.repo.url, f"HEAD:{ref}"
        )
        if not pushed.ok:
            if "stale info" in pushed.stderr or "rejected" in pushed.stderr:
                raise BranchMovedError(self.branch)
            raise RepositoryAccessError(classify(pushed))
        return sha

    def _inside(self, path: str) -> Path:
        # Les chemins viennent de noms validés ; la garde reste, au cas où une évolution
        # laisserait passer un `..` : on n'écrit jamais hors de la copie.
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("chemin hors de la copie de travail")
        return target


@asynccontextmanager
async def checkout(repo: Repository, access: GitAccess, branch: str) -> AsyncIterator[WorkCopy]:
    """Clone superficiel de `branch`, détruit à la sortie quoi qu'il arrive."""
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-copy-"))
    try:
        listed = await run_git(
            ["ls-remote", "--heads", repo.url, f"refs/heads/{branch}"], workdir, access
        )
        if not listed.ok:
            raise RepositoryAccessError(classify(listed))
        if not listed.stdout.strip():
            raise BranchMissingError(branch)
        root = workdir / "copy"
        cloned = await run_git(
            ["clone", "-q", "--depth", "1", "--branch", branch, repo.url, str(root)],
            workdir,
            access,
        )
        if not cloned.ok:
            raise RepositoryAccessError(classify(cloned))
        copy = WorkCopy(repo, access, branch, root)
        copy.head = (await copy.git("rev-parse", "HEAD")).stdout.strip()
        yield copy
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


def _read(path: Path) -> str | None:
    try:
        # newline="" : sans conversion de fins de ligne, comme à l'écriture.
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" : le contenu est écrit tel que fourni, sans conversion de fins de ligne,
    # pour que la relecture rende exactement ce qui a été déposé (critère 2).
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
