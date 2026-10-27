from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from miles_socle.secrets.model import Secret

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.graph import read_graph
from miles.git.worktree import RepositoryAccessError

TOKEN = GitAccess(token=Secret("jeton-local"))
WORKSPACE = "ams"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _repo(tmp_path: Path) -> tuple[Repository, Path]:
    """Dépôt nu et sa copie de travail, prêts à recevoir des commits."""
    bare, work = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(work))
    (work / "README.md").write_text("# essai")
    _git("-C", str(work), "add", "-A")
    _git("-C", str(work), *IDENTITY, "commit", "-q", "-m", "base")
    _git("-C", str(work), "push", "-q", str(bare), "main")
    return Repository(f"file://{bare}", "local", "remote"), work


def _commit(work: Path, message: str, name: str = "f.txt") -> None:
    (work / name).write_text(message)
    _git("-C", str(work), "add", "-A")
    _git("-C", str(work), *IDENTITY, "commit", "-q", "-m", message)


async def test_a_workspace_without_any_branch_gives_an_empty_graph(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)

    assert await read_graph(repo, TOKEN, WORKSPACE) == []


async def test_only_the_branches_of_this_workspace_are_read(tmp_path: Path) -> None:
    """Les branches d'un AUTRE workspace n'ont rien à faire dans ce graphe.

    Leurs COMMITS communs, eux, y sont : « base » est l'ancêtre dont part la branche du
    workspace, et l'omettre ferait partir sa voie de nulle part.
    """
    repo, work = _repo(tmp_path)
    bare = repo.url.removeprefix("file://")
    _git("-C", str(work), "checkout", "-q", "-b", "back/ams/root")
    _commit(work, "racine ams")
    _git("-C", str(work), "push", "-q", bare, "back/ams/root")
    _git("-C", str(work), "checkout", "-q", "-b", "back/autre/root")
    _commit(work, "racine autre")
    _git("-C", str(work), "push", "-q", bare, "back/autre/root")

    graph = await read_graph(repo, TOKEN, WORKSPACE)

    subjects = [c.subject for c in graph]
    assert "racine ams" in subjects
    # La branche d'un autre workspace n'est pas lue : sa référence n'est pas récupérée.
    assert "racine autre" not in subjects
    # « base » est en revanche l'ANCÊTRE de back/ams/root : l'histoire commune est
    # vraie, et la cacher laisserait une voie partir de nulle part.
    assert "base" in subjects
    assert all("back/autre/" not in ref for c in graph for ref in c.refs)


async def test_each_commit_carries_its_parents_and_the_branches_that_point_it(
    tmp_path: Path,
) -> None:
    repo, work = _repo(tmp_path)
    bare = repo.url.removeprefix("file://")
    _git("-C", str(work), "checkout", "-q", "-b", "back/ams/root")
    _commit(work, "premier")
    _commit(work, "second")
    _git("-C", str(work), "push", "-q", bare, "back/ams/root")

    graph = await read_graph(repo, TOKEN, WORKSPACE)

    assert [c.subject for c in graph[:2]] == ["second", "premier"]
    # La parenté est ce qui fait les voies : sans elle, rien à dessiner.
    assert graph[0].parents == (graph[1].sha,)
    assert "back/ams/root" in graph[0].refs
    assert graph[1].refs == ()
    assert graph[0].author == "t" and graph[0].written_at != ""


async def test_two_branches_share_their_common_ancestor(tmp_path: Path) -> None:
    repo, work = _repo(tmp_path)
    bare = repo.url.removeprefix("file://")
    _git("-C", str(work), "checkout", "-q", "-b", "back/ams/root")
    _commit(work, "ancetre")
    _git("-C", str(work), "push", "-q", bare, "back/ams/root")
    _git("-C", str(work), "checkout", "-q", "-b", "back/ams/essai")
    _commit(work, "sur essai")
    _git("-C", str(work), "push", "-q", bare, "back/ams/essai")

    graph = await read_graph(repo, TOKEN, WORKSPACE)

    by_subject = {c.subject: c for c in graph}
    assert by_subject["sur essai"].parents == (by_subject["ancetre"].sha,)
    assert "back/ams/essai" in by_subject["sur essai"].refs
    assert "back/ams/root" in by_subject["ancetre"].refs


async def test_the_depth_bounds_what_is_read_and_the_edge_shows_no_parent(
    tmp_path: Path,
) -> None:
    """La troncature se VOIT : la voie s'arrête, plutôt que de mentir sur une racine."""
    repo, work = _repo(tmp_path)
    bare = repo.url.removeprefix("file://")
    _git("-C", str(work), "checkout", "-q", "-b", "back/ams/root")
    for rank in range(5):
        _commit(work, f"commit {rank}")
    _git("-C", str(work), "push", "-q", bare, "back/ams/root")

    graph = await read_graph(repo, TOKEN, WORKSPACE, limit=2)

    assert len(graph) == 2
    assert graph[-1].parents == ()


async def test_an_unreachable_repository_designates_access(tmp_path: Path) -> None:
    repo = Repository(f"file://{tmp_path / 'disparu.git'}", "x", "disparu")

    with pytest.raises(RepositoryAccessError):
        await read_graph(repo, TOKEN, WORKSPACE)
