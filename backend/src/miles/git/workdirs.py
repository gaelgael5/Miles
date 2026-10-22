from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.rights import classify
from miles.git.runner import run_git
from miles.git.workcopy import BranchMissingError, WorkCopy
from miles.git.worktree import RepositoryAccessError

# Segments de chemin : un identifiant de workspace et un nom de branche déjà validés par
# leurs propres règles. Revalidés ici parce qu'ils deviennent des chemins sur le volume.
_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_REMOTE = "origin"


@dataclass
class WorkDirs:
    """Une copie persistante par branche de travail, sur le volume monté (Gael, 22/10/2026).

    Git fait foi : chaque geste commence par ramener la copie sur la tête distante
    (fetch, reset, clean), si bien qu'une modification faite dans GitHub est vue, et
    qu'un geste interrompu ne laisse rien au suivant. Le répertoire n'est qu'un cache
    qui évite de recloner ; le supprimer ne perd rien.
    """

    root: Path
    # Un geste à la fois par répertoire : deux requêtes sur la même branche se
    # piétineraient l'arbre de travail. Le back-office tourne en un seul processus.
    _locks: dict[Path, asyncio.Lock] = field(default_factory=dict)

    def directory(self, workspace_id: str, branch: str) -> Path:
        name = branch.removeprefix("work/")
        if not (_SEGMENT_RE.match(workspace_id) and _SEGMENT_RE.match(name)):
            raise ValueError("segment de copie de travail invalide")
        target = (self.root / workspace_id / name).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("copie de travail hors du volume")
        return target

    @asynccontextmanager
    async def checkout(
        self, repo: Repository, access: GitAccess, workspace_id: str, branch: str
    ) -> AsyncIterator[WorkCopy]:
        directory = self.directory(workspace_id, branch)
        lock = self._locks.setdefault(directory, asyncio.Lock())
        async with lock:
            copy = WorkCopy(repo, access, branch, directory)
            await _align(copy)
            yield copy


async def _align(copy: WorkCopy) -> None:
    """Amène la copie exactement sur la tête distante de sa branche."""
    ref = f"refs/heads/{copy.branch}"
    await asyncio.to_thread(copy.root.mkdir, parents=True, exist_ok=True)
    listed = await run_git(["ls-remote", "--heads", copy.repo.url, ref], copy.root, copy.access)
    if not listed.ok:
        raise RepositoryAccessError(classify(listed))
    if not listed.stdout.strip():
        raise BranchMissingError(copy.branch)
    if not (copy.root / ".git").is_dir():
        await _ok(copy, "init", "-q")
        await _ok(copy, "remote", "add", _REMOTE, copy.repo.url)
    # L'adresse est reposée à chaque geste : le dépôt d'un workspace peut changer, et le
    # jeton ne s'y écrit jamais (il passe par l'assistant d'identifiants du lanceur).
    await _ok(copy, "remote", "set-url", _REMOTE, copy.repo.url)
    tracking = f"refs/remotes/{_REMOTE}/{copy.branch}"
    await _ok(copy, "fetch", "-q", "--depth", "1", _REMOTE, f"+{ref}:{tracking}")
    # Forcé puis nettoyé : un geste interrompu a pu laisser un commit non poussé, des
    # modifications ou des fichiers non suivis ; aucun ne doit atteindre le geste suivant.
    await _ok(copy, "checkout", "-q", "-f", "-B", copy.branch, tracking)
    await _ok(copy, "clean", "-q", "-fdx")
    copy.head = (await copy.git("rev-parse", "HEAD")).stdout.strip()


async def _ok(copy: WorkCopy, *args: str) -> None:
    result = await copy.git(*args)
    if not result.ok:
        raise RepositoryAccessError(classify(result))
