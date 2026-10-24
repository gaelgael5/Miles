from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.workcopy import BranchMissingError, BranchMovedError, checkout
from miles.git.worktree import RepositoryAccessError
from miles.secrets.model import Secret

TOKEN = GitAccess(token=Secret("jeton-local"))
AUTHOR = "admin via Miles <admin@local.miles.invalid>"
BRANCH = "back/retrait/atelier"


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _repo(tmp_path: Path) -> Repository:
    """Dépôt nu portant main et la branche de travail, comme après son ouverture."""
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "manifest.json").write_text("{}")
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *identity, "commit", "-q", "-m", "base")
    _git("-C", str(seed), "push", "-q", str(bare), f"main:{BRANCH}", "main")
    return Repository(f"file://{bare}", "local", "remote")


def _bare(repo: Repository) -> str:
    return repo.url.removeprefix("file://")


async def test_written_file_is_pushed_byte_for_byte_and_read_back(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    content = "nom: colis\r\nversion: 1\n# é\n"

    async with checkout(repo, TOKEN, BRANCH) as copy:
        await copy.write("shared/messages/colis.yaml", content)
        commit = await copy.commit_push("Modèle", AUTHOR)
    async with checkout(repo, TOKEN, BRANCH) as copy:
        read = await copy.read("shared/messages/colis.yaml")
        paths = await copy.paths()

    assert read == content
    assert paths == ["manifest.json", "shared/messages/colis.yaml"]
    assert _git("--git-dir", _bare(repo), "rev-parse", BRANCH).strip() == commit
    assert _git("--git-dir", _bare(repo), "log", "-1", "--format=%an", BRANCH).strip() == (
        "admin via Miles"
    )
    # main n'est jamais touchée : on n'écrit que sur la branche de travail.
    assert _git("--git-dir", _bare(repo), "rev-list", "--count", "main").strip() == "1"


async def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    async with checkout(_repo(tmp_path), TOKEN, BRANCH) as copy:
        assert await copy.read("shared/messages/absent.yaml") is None


async def test_missing_branch_is_refused_and_never_created(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(BranchMissingError):
        async with checkout(repo, TOKEN, "back/retrait/absente"):
            pass

    assert "back/retrait/absente" not in _git("--git-dir", _bare(repo), "branch", "--list")


async def test_branch_moved_meanwhile_refuses_the_push_and_keeps_the_other_write(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    async with checkout(repo, TOKEN, BRANCH) as first:
        async with checkout(repo, TOKEN, BRANCH) as second:
            await second.write("a.yaml", "a")
            other = await second.commit_push("Autre écriture", AUTHOR)
        await first.write("b.yaml", "b")
        with pytest.raises(BranchMovedError):
            await first.commit_push("Écriture concurrente", AUTHOR)

    assert _git("--git-dir", _bare(repo), "rev-parse", BRANCH).strip() == other


async def test_branch_deleted_meanwhile_is_not_recreated(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    async with checkout(repo, TOKEN, BRANCH) as copy:
        _git("--git-dir", _bare(repo), "branch", "-D", BRANCH)
        await copy.write("a.yaml", "a")
        with pytest.raises(BranchMovedError):
            await copy.commit_push("Écriture", AUTHOR)

    assert BRANCH not in _git("--git-dir", _bare(repo), "branch", "--list")


async def test_unreachable_repository_designates_the_access(tmp_path: Path) -> None:
    repo = Repository(f"file://{tmp_path}/absent.git", "local", "absent")

    with pytest.raises(RepositoryAccessError):
        async with checkout(repo, TOKEN, BRANCH):
            pass


async def test_path_outside_the_copy_is_refused(tmp_path: Path) -> None:
    async with checkout(_repo(tmp_path), TOKEN, BRANCH) as copy:
        with pytest.raises(ValueError, match="hors de la copie"):
            await copy.write("../evasion.yaml", "x")
