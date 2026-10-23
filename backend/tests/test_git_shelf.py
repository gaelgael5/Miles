from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from miles.git.holdspace import HoldSpaces
from miles.git.shelf import ShelfMissingError, ShelfTakenError, drop_shelf, merge_shelf, shelve
from tests.test_git_holdspace import BRANCH, IDENTITY, LEA, TOKEN, _edit, _git, _remote

SHELF = "shelve/lea/edition"


def _tip(bare: str, ref: str) -> str | None:
    out = subprocess.run(  # noqa: S603
        ["git", "--git-dir", bare, "rev-parse", "--verify", "-q", ref],  # noqa: S607
        capture_output=True,
        text=True,
    )
    return out.stdout.strip() or None


def _outside(seed: Path, bare: str, path: str, content: str) -> None:
    (seed / path).write_text(content)
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *IDENTITY, "commit", "-qm", "hors Miles")
    _git("-C", str(seed), "push", "-q", bare, f"main:{BRANCH}")


async def test_shelving_pushes_the_head_and_never_overwrites_an_existing_shelf(
    tmp_path: Path,
) -> None:
    repo, _, head = _remote(tmp_path)
    bare = repo.url.removeprefix("file://")
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _edit(spaces, repo, head, "deux\n")

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        shelved = await shelve(c, SHELF)
        await c.write("a.yaml", "trois\n")
        await c.commit_local("encore")
        with pytest.raises(ShelfTakenError):
            await shelve(c, SHELF)

    assert shelved == mine == _tip(bare, SHELF)
    assert _tip(bare, BRANCH) == head


async def test_resuming_merges_the_shelf_into_the_moved_branch_then_drops_it(
    tmp_path: Path,
) -> None:
    repo, seed, head = _remote(tmp_path)
    bare = repo.url.removeprefix("file://")
    first = HoldSpaces(tmp_path / "tenues")
    await _edit(first, repo, head, "deux\n")
    async with first.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        await shelve(c, SHELF)
    await first.discard("retrait", "edition")
    _outside(seed, bare, "b.yaml", "ailleurs\n")
    moved = _tip(bare, BRANCH)
    assert moved is not None

    async with first.open(repo, TOKEN, "retrait", "edition", published=moved, signature=LEA) as c:
        tip, conflicts = await merge_shelf(c, SHELF)
        await drop_shelf(c, SHELF, tip)
        merged = (await c.read("a.yaml"), await c.read("b.yaml"))
        pending = await c.unpublished()

    assert conflicts == []
    assert merged == ("deux\n", "ailleurs\n")
    assert pending >= 1
    assert _tip(bare, SHELF) is None
    assert _tip(bare, BRANCH) == moved


async def test_a_conflicting_shelf_names_the_files_and_writes_nothing(tmp_path: Path) -> None:
    repo, seed, head = _remote(tmp_path)
    bare = repo.url.removeprefix("file://")
    spaces = HoldSpaces(tmp_path / "tenues")
    await _edit(spaces, repo, head, "deux\n")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        await shelve(c, SHELF)
    await spaces.discard("retrait", "edition")
    _outside(seed, bare, "a.yaml", "autre chose\n")
    moved = _tip(bare, BRANCH)
    assert moved is not None

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=moved, signature=LEA) as c:
        _, conflicts = await merge_shelf(c, SHELF)
        after = (c.head, await c.read("a.yaml"), await c.unpublished())

    assert conflicts == ["a.yaml"]
    assert after == (moved, "autre chose\n", 0)
    assert _tip(bare, SHELF) is not None


async def test_a_shelf_removed_from_the_forge_is_said_missing(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        with pytest.raises(ShelfMissingError):
            await merge_shelf(c, SHELF)
