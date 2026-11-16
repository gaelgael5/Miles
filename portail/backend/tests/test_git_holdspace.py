from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from miles_socle.git.access import GitAccess
from miles_socle.git.forge import Repository
from miles_socle.secrets.model import Secret

from miles.git.holdspace import HoldSpaces
from miles.git.workcopy import BranchMissingError, BranchMovedError, WorkCopy

TOKEN = GitAccess(token=Secret("jeton-de-lea"))
LEA = "Léa Martin <lea@forge.invalid>"
BRANCH = "back/retrait/edition"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _remote(tmp_path: Path) -> tuple[Repository, Path, str]:
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "a.yaml").write_text("un\n")
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *IDENTITY, "commit", "-q", "-m", "base")
    _git("-C", str(seed), "push", "-q", str(bare), f"main:{BRANCH}")
    head = _git("-C", str(seed), "rev-parse", "HEAD").strip()
    return Repository(f"file://{bare}", "local", "remote"), seed, head


def _remote_head(repo: Repository) -> str:
    return _git("--git-dir", repo.url.removeprefix("file://"), "rev-parse", BRANCH).strip()


async def _edit(spaces: HoldSpaces, repo: Repository, published: str, content: str) -> str:
    async with spaces.open(
        repo, TOKEN, "retrait", "edition", published=published, signature=LEA
    ) as copy:
        await copy.write("a.yaml", content)
        return await copy.commit_local("modification")


async def test_a_commit_stays_local_and_is_signed_by_the_person_as_author_and_committer(
    tmp_path: Path,
) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")

    commit = await _edit(spaces, repo, head, "deux\n")
    space = spaces.directory("retrait", "edition")
    who = _git("-C", str(space), "log", "-1", "--format=%an <%ae>|%cn <%ce>", commit).strip()

    assert _remote_head(repo) == head
    assert who == f"{LEA}|{LEA}"
    assert space == (tmp_path / "tenues" / "retrait" / "edition").resolve()
    assert "jeton-de-lea" not in (space / ".git" / "config").read_text()


async def test_local_commits_survive_between_gestures_but_leftovers_do_not(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    await _edit(spaces, repo, head, "deux\n")

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        await c.write("a.yaml", "interrompu, jamais commité\n")
        await c.write("orphelin.yaml", "x\n")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        assert await c.read("a.yaml") == "deux\n"
        assert await c.read("orphelin.yaml") is None
        assert await c.unpublished() == 1


async def test_publish_pushes_the_local_commits_then_nothing_is_left_to_publish(
    tmp_path: Path,
) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    await _edit(spaces, repo, head, "deux\n")
    last = await _edit(spaces, repo, head, "trois\n")

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        assert await c.unpublished() == 2
        published = await c.publish()
        assert await c.unpublished() == 0
        # Rejeu : rien à pousser, la tête reste la même.
        assert await c.publish() == published

    assert published == last == _remote_head(repo)


async def test_publish_refuses_when_the_branch_moved_and_keeps_the_local_commits(
    tmp_path: Path,
) -> None:
    repo, seed, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _edit(spaces, repo, head, "deux\n")
    (seed / "a.yaml").write_text("hors Miles\n")
    _git("-C", str(seed), *IDENTITY, "commit", "-qam", "hors Miles")
    _git("-C", str(seed), "push", "-q", repo.url.removeprefix("file://"), f"main:{BRANCH}")
    moved = _remote_head(repo)

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        with pytest.raises(BranchMovedError):
            await c.publish()
        assert c.head == mine
        assert await c.unpublished() == 1

    assert _remote_head(repo) == moved


async def test_a_discarded_space_is_gone_and_reopens_from_the_forge(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    await _edit(spaces, repo, head, "deux\n")

    await spaces.discard("retrait", "edition")
    gone = not spaces.directory("retrait", "edition").exists()
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        content = await c.read("a.yaml")

    assert gone
    assert content == "un\n"


@pytest.mark.parametrize("segment", ["..", "A", "_x", "a/b"])
def test_a_space_path_never_leaves_the_volume(tmp_path: Path, segment: str) -> None:
    with pytest.raises(ValueError, match="invalide"):
        HoldSpaces(tmp_path).directory("retrait", segment)


async def test_with_nothing_pending_the_space_follows_a_change_made_in_the_forge(
    tmp_path: Path,
) -> None:
    repo, seed, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    _push_outside(seed, repo)
    moved = _remote_head(repo)

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        assert (c.head, c.published) == (moved, moved)
        assert await c.read("a.yaml") == "hors Miles\n"
        assert await c.unpublished() == 0


async def test_with_commits_pending_the_space_stays_put_until_publication_says_so(
    tmp_path: Path,
) -> None:
    repo, seed, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _edit(spaces, repo, head, "deux\n")
    _push_outside(seed, repo)

    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        assert (c.head, c.published) == (mine, head)
        assert await c.read("a.yaml") == "deux\n"


def _push_outside(seed: Path, repo: Repository) -> None:
    (seed / "a.yaml").write_text("hors Miles\n")
    _git("-C", str(seed), *IDENTITY, "commit", "-qam", "hors Miles")
    _git("-C", str(seed), "push", "-q", repo.url.removeprefix("file://"), f"main:{BRANCH}")


def _compte_git(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Les sous-commandes git qu'un geste sur la branche tenue lance réellement.

    On compte, on ne chronomètre pas (bug 347ffd22, critère 1) : sur une forge `file://`
    locale un `fetch` coûte quelques millisecondes, et un test au chronomètre resterait
    vert le jour où le `fetch` inutile revient. Ce qu'on protège est un aller-retour
    réseau vers la forge.
    """
    appels: list[str] = []
    origine = WorkCopy.git

    async def compte(self: WorkCopy, *args: str) -> object:
        appels.append(args[0])
        return await origine(self, *args)

    monkeypatch.setattr(WorkCopy, "git", compte)
    return appels


async def test_a_second_gesture_on_an_unchanged_held_branch_fetches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass

    appels = _compte_git(monkeypatch)
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        contenu = await c.read("a.yaml")
        tenue = (c.head, c.published)

    assert "fetch" not in appels
    # La forge est TOUJOURS interrogée : c'est ce qui distingue l'économie d'un cache.
    assert appels.count("ls-remote") == 1
    assert (contenu, tenue) == ("un\n", (head, head))


async def test_two_identical_gestures_in_a_row_ask_the_forge_once_each_and_never_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass

    appels = _compte_git(monkeypatch)
    for _ in range(2):
        async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
            pass

    assert (appels.count("ls-remote"), appels.count("fetch")) == (2, 0)


async def test_a_held_branch_moved_on_the_forge_is_fetched_and_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, seed, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    _push_outside(seed, repo)
    moved = _remote_head(repo)

    appels = _compte_git(monkeypatch)
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        contenu = await c.read("a.yaml")
        tenue = (c.head, c.published)

    assert "fetch" in appels
    assert (contenu, tenue) == ("hors Miles\n", (moved, moved))


async def test_with_commits_pending_the_gesture_does_not_even_ask_the_forge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le `fetch` sauté ne doit pas l'être pour la mauvaise raison (critère 3).

    Avec du travail en attente, rien ne bouge AVANT toute interrogation : c'est une
    décision, distincte de l'économie faite quand il n'y a rien à récupérer. Les deux
    produisent le même effet visible et se confondraient dans un seul test.
    """
    repo, seed, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _edit(spaces, repo, head, "deux\n")
    _push_outside(seed, repo)

    appels = _compte_git(monkeypatch)
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        tenue = (c.head, c.published)

    assert "fetch" not in appels and "ls-remote" not in appels
    assert tenue == (mine, head)


async def test_a_branch_deleted_on_the_forge_during_the_hold_is_named_as_missing(
    tmp_path: Path,
) -> None:
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    _git("-C", repo.url.removeprefix("file://"), "branch", "-D", BRANCH)

    with pytest.raises(BranchMissingError):
        async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
            pass


async def test_a_space_absent_from_the_volume_still_clones_from_the_forge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans référence de suivi, l'économie ne se décide pas : on récupère (critère 5)."""
    repo, _, head = _remote(tmp_path)
    spaces = HoldSpaces(tmp_path / "tenues")

    appels = _compte_git(monkeypatch)
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA) as c:
        contenu = await c.read("a.yaml")

    assert "fetch" in appels
    assert (contenu, c.head) == ("un\n", head)
