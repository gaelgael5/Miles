"""Graphe des commits des branches d'un workspace (Gael, 24/10/2026).

Sert la vue « ferroviaire » : les branches côte à côte, leurs commits et leurs liens de
parenté, comme un historique git dessiné en voies.

Lecture DÉDIÉE, et non une copie de travail : toutes les copies de Miles sont clonées en
`--depth 1`, ce qui suffit à lire et écrire du paramétrage mais ne montre aucune
parenté. Ici il faut l'inverse — de la profondeur, et aucun contenu de fichier.

D'où le dépôt nu, le `--filter=blob:none` (on ne veut pas les blobs) et la profondeur
bornée : un graphe se regarde sur quelques dizaines de commits, pas sur toute la vie du
dépôt. Les commits de la frontière n'affichent aucun parent — c'est la troncature, et
elle se voit à l'écran plutôt que de mentir sur une racine.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.rights import classify
from miles.git.runner import run_git
from miles.git.worktree import RepositoryAccessError, work_branch_prefix

# Plafond dur : au-delà, un graphe n'est plus lisible et la lecture coûte pour rien.
MAX_COMMITS = 500
DEFAULT_COMMITS = 100
# Séparateurs improbables dans un message de commit, et jamais dans un sha ni une date.
_FIELD = "\x1f"
_FORMAT = _FIELD.join(["%H", "%P", "%an", "%aI", "%s", "%D"])


@dataclass(frozen=True)
class CommitNode:
    sha: str
    # Vide quand le commit est à la frontière de la profondeur lue : la voie s'arrête là.
    parents: tuple[str, ...]
    author: str
    written_at: str
    subject: str
    # Branches qui pointent ce commit, en noms courts (« back/ams/root »).
    refs: tuple[str, ...]


async def read_graph(
    repo: Repository, access: GitAccess, workspace_id: str, limit: int = DEFAULT_COMMITS
) -> list[CommitNode]:
    """Les commits des branches de CE workspace, du plus récent au plus ancien."""
    depth = max(1, min(limit, MAX_COMMITS))
    prefix = work_branch_prefix(workspace_id)
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-graph-"))
    try:
        # Demandé AVANT de récupérer : `git fetch` échoue quand aucune référence ne
        # correspond, et ce refus ressemblerait à un défaut d'accès alors que le
        # workspace n'a simplement aucune branche.
        heads = await run_git(
            ["ls-remote", "--heads", repo.url, f"refs/heads/{prefix}*"], workdir, access
        )
        if not heads.ok:
            raise RepositoryAccessError(classify(heads))
        if not heads.stdout.strip():
            return []
        started = await run_git(["init", "-q", "--bare", "."], workdir, access)
        if not started.ok:
            raise RepositoryAccessError(classify(started))
        # Les refs sont recopiées telles quelles : `%D` rendra donc les noms de branches
        # du dépôt, ceux que la personne lit sur la forge.
        fetched = await run_git(
            [
                "fetch",
                "-q",
                "--filter=blob:none",
                "--no-tags",
                "--depth",
                str(depth),
                repo.url,
                f"+refs/heads/{prefix}*:refs/heads/{prefix}*",
            ],
            workdir,
            access,
        )
        if not fetched.ok:
            raise RepositoryAccessError(classify(fetched))
        listed = await run_git(
            # `--decorate=full` : sans lui, `%D` ne rend RIEN, et on perdrait les
            # branches qui pointent chaque commit — ce qui fait les voies.
            [
                "log",
                "--all",
                "--date-order",
                "--decorate=full",
                f"--format={_FORMAT}",
                "-n",
                str(depth),
            ],
            workdir,
            access,
        )
        if not listed.ok:
            # Dépôt sans aucune branche de ce workspace : `log` échoue faute de référence,
            # et c'est un graphe vide, pas une panne d'accès.
            return []
        return [node for line in listed.stdout.splitlines() if (node := _node(line)) is not None]
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


def _node(line: str) -> CommitNode | None:
    fields = line.split(_FIELD)
    if len(fields) != 6:
        return None
    sha, parents, author, written_at, subject, refs = fields
    return CommitNode(
        sha,
        tuple(p for p in parents.split() if p),
        author,
        written_at,
        subject,
        _refs(refs),
    )


def _refs(raw: str) -> tuple[str, ...]:
    """Les branches qui pointent le commit, nettoyées de ce que `%D` ajoute.

    `%D` rend « HEAD -> refs/heads/x, refs/heads/y » : on ne garde que les branches, et
    sous leur nom court, puisque c'est ainsi qu'elles s'affichent.
    """
    names = []
    for part in raw.split(", "):
        name = part.split(" -> ")[-1].strip()
        if name.startswith("refs/heads/"):
            names.append(name.removeprefix("refs/heads/"))
    return tuple(names)
