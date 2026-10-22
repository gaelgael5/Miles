from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.versions import fetch_versions, tag_head
from miles.git.workcopy import BranchMissingError
from miles.git.workdirs import WorkDirs
from miles.secrets.model import Secret

TOKEN = GitAccess(token=Secret("jeton-local"))
AUTHOR = "alice via Miles <alice@annuaire.miles.invalid>"
BRANCH = "work/atelier"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _remote(tmp_path: Path) -> tuple[Repository, Path]:
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "a.yaml").write_text("un\n")
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *IDENTITY, "commit", "-q", "-m", "base")
    _git("-C", str(seed), "push", "-q", str(bare), f"main:{BRANCH}")
    return Repository(f"file://{bare}", "local", "remote"), seed


def _outside_change(seed: Path, bare: str, content: str) -> None:
    (seed / "a.yaml").write_text(content)
    _git("-C", str(seed), *IDENTITY, "commit", "-qam", "hors Miles")
    _git("-C", str(seed), "push", "-q", bare, f"main:{BRANCH}")


async def test_copy_lives_in_its_branch_directory_and_follows_the_forge(tmp_path: Path) -> None:
    repo, seed = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        first = await copy.read("a.yaml")
        root = copy.root
    _outside_change(seed, repo.url.removeprefix("file://"), "deux\n")
    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        second = await copy.read("a.yaml")

    assert root == (tmp_path / "volume" / "retrait" / "atelier").resolve()
    assert (first, second) == ("un\n", "deux\n")
    assert "jeton-local" not in (root / ".git" / "config").read_text()


async def test_leftovers_of_an_interrupted_gesture_never_reach_the_next(tmp_path: Path) -> None:
    repo, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        await copy.write("a.yaml", "modifié sans push\n")
        await copy.write("orphelin.yaml", "x\n")
        await copy.git("add", "-A")
        await copy.git(*IDENTITY, "commit", "-qm", "jamais poussé")
    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        assert await copy.read("a.yaml") == "un\n"
        assert await copy.read("orphelin.yaml") is None
        assert await copy.paths() == ["a.yaml"]


async def test_uncommitted_changes_and_untracked_files_are_dropped(tmp_path: Path) -> None:
    repo, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        await copy.write("a.yaml", "modifié, jamais commité\n")
        await copy.write("domains/x/orphelin.yaml", "x\n")
    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        assert await copy.read("a.yaml") == "un\n"
        assert not (copy.root / "domains").exists()


async def test_written_change_is_pushed_and_seen_by_a_fresh_copy(tmp_path: Path) -> None:
    repo, _ = _remote(tmp_path)

    async with WorkDirs(tmp_path / "v1").checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        await copy.write("a.yaml", "écrit\n")
        await copy.commit_push("Écriture", AUTHOR)
    async with WorkDirs(tmp_path / "v2").checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        assert await copy.read("a.yaml") == "écrit\n"


async def test_missing_branch_is_named_and_never_recreated(tmp_path: Path) -> None:
    repo, _ = _remote(tmp_path)

    with pytest.raises(BranchMissingError):
        async with WorkDirs(tmp_path / "volume").checkout(repo, TOKEN, "retrait", "work/absente"):
            pass

    assert "work/absente" not in _git("-C", repo.url.removeprefix("file://"), "branch")


@pytest.mark.parametrize(
    ("workspace", "branch"),
    [("..", BRANCH), ("retrait", "work/.."), ("Retrait", BRANCH), ("retrait", "work/a/b")],
)
def test_path_segments_are_checked_before_any_directory(workspace: str, branch: str) -> None:
    with pytest.raises(ValueError, match="segment"):
        WorkDirs(Path("/volume")).directory(workspace, branch)


async def test_a_version_deleted_on_the_forge_leaves_the_persistent_copy(tmp_path: Path) -> None:
    repo, _ = _remote(tmp_path)
    bare = repo.url.removeprefix("file://")
    dirs = WorkDirs(tmp_path / "volume")
    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        await tag_head(copy, 1, "Première", AUTHOR)
        await tag_head(copy, 2, "Seconde", AUTHOR)
        assert [v.number for v in await fetch_versions(copy)] == [2, 1]
    _git("-C", bare, "tag", "-d", "version/2")

    async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
        assert [v.number for v in await fetch_versions(copy)] == [1]
