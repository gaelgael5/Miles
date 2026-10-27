from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from miles_socle.secrets.model import Secret

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.rights import Reason, Right, classify, run_access_check, verification_name
from miles.git.runner import GitResult

TOKEN = GitAccess(token=Secret("jeton-sans-usage-en-local"))
SUFFIX = "0a1b2c3d"
BRANCH = f"miles-verification-{SUFFIX}"


def _bare(tmp_path: Path, hook: str | None = None) -> Repository:
    # Vrai dépôt git, servi par le protocole file:// : le parcours de push, tag et
    # suppression est celui qu'emprunte une forge, sans réseau.
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603, S607
    if hook is not None:
        script = bare / "hooks" / "pre-receive"
        script.write_text(f"#!/bin/sh\n{hook}\n")
        script.chmod(0o755)
    return Repository(f"file://{bare}", "local", "remote")


def _refs(repo: Repository) -> str:
    path = repo.url.removeprefix("file://")
    command = ["git", "--git-dir", path, "for-each-ref"]
    out = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    return out.stdout


async def test_empty_repository_gets_main_first_then_all_rights_pass(tmp_path: Path) -> None:
    repo = _bare(tmp_path)

    report = await run_access_check(repo, TOKEN, SUFFIX)

    assert [c.right for c in report.checks] == list(Right)
    assert report.all_passed
    assert (report.branch, report.residual_branch, report.residual_tag) == (BRANCH, None, None)
    # Seul effet durable : main, posée pour que la vérification reste supprimable.
    assert report.initialized_branch == "main"
    assert [line.split()[-1] for line in _refs(repo).splitlines()] == ["refs/heads/main"]


async def test_protected_verification_branch_is_named_as_protection(tmp_path: Path) -> None:
    # Hook qui refuse toute écriture sur les branches de vérification : l'équivalent
    # d'une règle de protection posée sur le motif.
    repo = _bare(tmp_path, 'echo "protected branch hook" >&2; exit 1')

    report = await run_access_check(repo, TOKEN, SUFFIX)

    failed = report.failed()
    assert failed is not None
    assert (failed.right, failed.reason) == (Right.CREATE_BRANCH, Reason.PROTECTED)
    assert not report.all_passed


async def test_branch_left_behind_is_reported_with_its_exact_name(tmp_path: Path) -> None:
    # Création admise, suppression refusée : la branche reste, et son nom est rendu.
    hook = (
        'while read old new ref; do [ "$new" = "$(printf "%040d" 0)" ]'
        ' && { echo "deletion denied" >&2; exit 1; }; done; exit 0'
    )
    repo = _bare(tmp_path, hook)

    report = await run_access_check(repo, TOKEN, SUFFIX)

    assert report.residual_branch == BRANCH
    assert report.residual_tag == BRANCH
    assert report.failed() is not None
    assert BRANCH in _refs(repo)


async def test_missing_repository_fails_on_read(tmp_path: Path) -> None:
    repo = Repository(f"file://{tmp_path / 'absent.git'}", "x", "absent")

    report = await run_access_check(repo, TOKEN, SUFFIX)

    assert [c.right for c in report.checks] == [Right.READ]
    assert not report.checks[0].ok


def _push_main(repo: Repository, work: Path) -> None:
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (
        ["init", "-q", "-b", "main", str(work)],
        ["-C", str(work), *identity, "commit", "-q", "--allow-empty", "-m", "x"],
        ["-C", str(work), "push", "-q", repo.url, "main"],
    ):
        subprocess.run(["git", *args], check=True)  # noqa: S603, S607


async def test_existing_branches_are_counted_not_overwritten(tmp_path: Path) -> None:
    repo = _bare(tmp_path)
    _push_main(repo, tmp_path / "work")

    report = await run_access_check(repo, TOKEN, SUFFIX)

    assert report.all_passed
    assert report.existing_branches == 1
    assert report.initialized_branch is None
    assert "refs/heads/main" in _refs(repo) and BRANCH not in _refs(repo)


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("remote: error: GH006: Protected branch update failed", Reason.PROTECTED),
        ("! [remote rejected] x -> x (pre-receive hook declined)", Reason.PROTECTED),
        ("remote: Repository not found.", Reason.REPOSITORY_NOT_FOUND),
        ("fatal: Authentication failed for 'https://github.com/a/b.git/'", Reason.CREDENTIALS),
        ("remote: Permission to a/b.git denied to bot.", Reason.FORBIDDEN),
        ("The requested URL returned error: 403", Reason.FORBIDDEN),
        ("fatal: unable to access 'x': Could not resolve host: github.com", Reason.UNREACHABLE),
        ("The requested URL returned error: 400", Reason.FAILED),
        ("quelque chose d'imprévu", Reason.FAILED),
    ],
)
def test_git_errors_are_classified(stderr: str, reason: Reason) -> None:
    assert classify(GitResult(1, "", stderr)) is reason


def test_verification_name_refuses_free_suffixes() -> None:
    assert verification_name(SUFFIX) == BRANCH
    with pytest.raises(ValueError):
        verification_name("../main")
