from __future__ import annotations

import re
from dataclasses import dataclass

from miles.git.rights import classify
from miles.git.workcopy import WorkCopy
from miles.git.worktree import RepositoryAccessError

# Identifiant complet : un préfixe court ne se récupère pas d'une forge, et deux
# commits pourraient le partager.
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class CommitNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    """Le paramétrage tel qu'il était à un commit, en lecture seule (ticket 28f00c74)."""

    copy: WorkCopy
    commit: str

    async def paths(self) -> list[str]:
        listed = await self.copy.git("ls-tree", "-r", "-z", "--name-only", self.commit)
        return sorted(p for p in listed.stdout.split("\0") if p)

    async def read(self, path: str) -> str | None:
        shown = await self.copy.git("show", f"{self.commit}:{path}")
        return shown.stdout if shown.ok else None


async def snapshot(copy: WorkCopy, commit: str) -> Snapshot:
    """Récupère `commit` dans la copie, sans toucher à son arbre de travail."""
    if not COMMIT_RE.match(commit):
        raise CommitNotFoundError(commit)
    if commit != copy.head:
        fetched = await copy.git("fetch", "-q", "--depth", "1", "origin", commit)
        if not fetched.ok:
            # La forge ne livre pas un commit qu'elle ne connaît pas : indiscernable ici
            # d'un commit jamais poussé, et c'est le même refus pour l'appelant.
            if "not our ref" in fetched.stderr or "couldn't find remote ref" in fetched.stderr:
                raise CommitNotFoundError(commit)
            raise RepositoryAccessError(classify(fetched))
    exists = await copy.git("cat-file", "-e", f"{commit}^{{commit}}")
    if not exists.ok:
        raise CommitNotFoundError(commit)
    return Snapshot(copy, commit)
