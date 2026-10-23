from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.worktree import (
    BranchExistsError,
    NonConformTreeError,
    RepositoryAccessError,
    diagnose,
    is_blank,
    open_work_branch,
)
from miles.secrets.model import Secret

TOKEN = GitAccess(token=Secret("jeton-local"))
AUTHOR = "admin via Miles <admin@local.miles.invalid>"
VALID_MANIFEST = json.dumps({"format_version": 1, "min_app_version": None, "capabilities": []})


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _repo(tmp_path: Path, files: dict[str, str]) -> Repository:
    """Dépôt nu dont main porte `files` ; HEAD pointe main, comme chez une forge."""
    bare, work = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(work))
    for path, content in files.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git("-C", str(work), "add", "-A")
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    _git("-C", str(work), *identity, "commit", "-q", "--allow-empty", "-m", "base")
    _git("-C", str(work), "push", "-q", str(bare), "main")
    return Repository(f"file://{bare}", "local", "remote")


def _tree(repo: Repository, ref: str) -> list[str]:
    bare = repo.url.removeprefix("file://")
    return _git("--git-dir", bare, "ls-tree", "-r", "--name-only", ref).split()


def _count(repo: Repository, ref: str) -> int:
    return int(_git("--git-dir", repo.url.removeprefix("file://"), "rev-list", "--count", ref))


def _seed_branch(repo: Repository, branch: str, files: dict[str, str], tmp_path: Path) -> None:
    """Pose `branch` dans le dépôt nu avec exactement `files` : la branche qui préexiste."""
    bare = repo.url.removeprefix("file://")
    work = tmp_path / f"seed-{branch.replace('/', '-')}"
    _git("init", "-q", "-b", "tmp", str(work))
    for path, content in files.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git("-C", str(work), "add", "-A")
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    _git("-C", str(work), *identity, "commit", "-q", "--allow-empty", "-m", "preexistante")
    _git("-C", str(work), "push", "-q", bare, f"HEAD:refs/heads/{branch}")


async def test_blank_repository_gets_the_skeleton_and_a_valid_manifest(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"README.md": "# Config"})

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR)

    assert (opened.branch, opened.outcome) == ("work/atelier", "initialisee")
    tree = _tree(repo, "work/atelier")
    assert "manifest.json" in tree and "README.md" in tree
    assert {"contracts/.gitkeep", "domains/.gitkeep", "shared/messages/.gitkeep"} <= set(tree)
    assert not any(p.startswith(("prod", "recette")) for p in tree)
    bare = repo.url.removeprefix("file://")
    manifest = json.loads(_git("--git-dir", bare, "show", "work/atelier:manifest.json"))
    assert diagnose(tree, json.dumps(manifest)).conform
    # Un commit, identifiable, au nom de la personne ; main n'a pas bougé.
    assert _count(repo, "work/atelier") == 2 and _count(repo, "main") == 1
    author = _git("--git-dir", bare, "log", "-1", "--format=%an <%ae>|%s", "work/atelier")
    assert author == f"{AUTHOR}|Initialisation de l'arborescence de paramétrage\n"


async def test_conform_repository_is_not_overwritten(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path, {"manifest.json": VALID_MANIFEST, "domains/retrait/screens/a.json": "{}"}
    )

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR)

    assert opened.outcome == "conforme"
    assert _count(repo, "work/atelier") == 1
    assert _tree(repo, "work/atelier") == _tree(repo, "main")


@pytest.mark.parametrize(
    ("files", "unexpected", "env_dirs", "manifest"),
    [
        ({"manifest.json": VALID_MANIFEST, "src/app.py": ""}, ["src/app.py"], [], "valide"),
        ({"manifest.json": VALID_MANIFEST, "prod/screens.json": ""}, [], ["prod"], "valide"),
        ({"domains/retrait/screens/a.json": "{}"}, [], [], "absent"),
        ({"manifest.json": "{pas du json", "domains/.gitkeep": ""}, [], [], "invalide"),
        (
            {"manifest.json": VALID_MANIFEST, "domains/retrait/autre/x": ""},
            ["domains/retrait/autre/x"],
            [],
            "valide",
        ),
    ],
)
async def test_non_conform_repository_is_diagnosed_and_left_untouched(
    tmp_path: Path,
    files: dict[str, str],
    unexpected: list[str],
    env_dirs: list[str],
    manifest: str,
) -> None:
    repo = _repo(tmp_path, files)

    with pytest.raises(NonConformTreeError) as caught:
        await open_work_branch(repo, TOKEN, "atelier", AUTHOR)

    diagnosis = caught.value.diagnosis
    assert (diagnosis.unexpected, diagnosis.environment_dirs, diagnosis.manifest) == (
        unexpected,
        env_dirs,
        manifest,
    )
    assert "work/atelier" not in _git("--git-dir", repo.url.removeprefix("file://"), "branch")


async def test_existing_branch_name_is_refused_without_touching_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})
    await open_work_branch(repo, TOKEN, "atelier", AUTHOR)
    before = _count(repo, "work/atelier")

    with pytest.raises(BranchExistsError):
        await open_work_branch(repo, TOKEN, "atelier", AUTHOR)

    assert _count(repo, "work/atelier") == before


async def test_existing_conform_branch_is_taken_over_without_writing_to_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})
    await open_work_branch(repo, TOKEN, "atelier", AUTHOR)
    before_count, before_tree = _count(repo, "work/atelier"), _tree(repo, "work/atelier")

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR, adopt_existing=True)

    assert (opened.branch, opened.outcome) == ("work/atelier", "reprise")
    # « elle n'a pas été touchée » doit rester vrai : ni commit de plus, ni fichier changé.
    assert _count(repo, "work/atelier") == before_count
    assert _tree(repo, "work/atelier") == before_tree


async def test_taking_over_keeps_the_branch_content_not_the_default_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"manifest.json": VALID_MANIFEST, "domains/depuis-main/.gitkeep": ""})
    _seed_branch(
        repo,
        "work/atelier",
        {"manifest.json": VALID_MANIFEST, "domains/depuis-la-branche/.gitkeep": ""},
        tmp_path,
    )

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR, adopt_existing=True)

    assert opened.outcome == "reprise"
    # Partir de la branche par défaut l'écraserait à la poussée : c'est le défaut guetté.
    assert _tree(repo, "work/atelier") == ["domains/depuis-la-branche/.gitkeep", "manifest.json"]


async def test_taking_over_a_blank_branch_gives_it_the_skeleton(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})
    _seed_branch(repo, "work/atelier", {"README.md": "# rien de Miles"}, tmp_path)

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR, adopt_existing=True)

    # Pas « initialisee » : le journal doit garder que la branche préexistait.
    assert opened.outcome == "reprise_initialisee"
    tree = _tree(repo, "work/atelier")
    assert "manifest.json" in tree and "README.md" in tree


async def test_taking_over_a_non_conform_branch_is_refused_and_leaves_it_untouched(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, {})
    _seed_branch(
        repo, "work/atelier", {"manifest.json": VALID_MANIFEST, "src/app.py": ""}, tmp_path
    )
    before = _count(repo, "work/atelier")

    with pytest.raises(NonConformTreeError) as caught:
        await open_work_branch(repo, TOKEN, "atelier", AUTHOR, adopt_existing=True)

    assert caught.value.diagnosis.unexpected == ["src/app.py"]
    assert _count(repo, "work/atelier") == before


async def test_taking_over_a_branch_that_vanished_opens_it_normally(tmp_path: Path) -> None:
    """La confirmation et la reprise sont deux appels : la branche peut disparaître entre eux."""
    repo = _repo(tmp_path, {"README.md": "# Config"})

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR, adopt_existing=True)

    assert (opened.branch, opened.outcome) == ("work/atelier", "initialisee")


async def test_a_branch_whose_name_merely_starts_the_same_is_not_mistaken_for_it(
    tmp_path: Path,
) -> None:
    """« work/atelier » n'existe pas parce que « work/atelier-bis » existe (relevé en revue).

    La confusion rendait la branche inouvrable : refus à l'ouverture, puis échec d'accès
    à la reprise, le clone visant une branche absente.
    """
    repo = _repo(tmp_path, {"README.md": "# Config"})
    _seed_branch(repo, "work/atelier-bis", {"manifest.json": VALID_MANIFEST}, tmp_path)

    opened = await open_work_branch(repo, TOKEN, "atelier", AUTHOR)

    assert (opened.branch, opened.outcome) == ("work/atelier", "initialisee")

async def test_unreachable_repository_designates_access(tmp_path: Path) -> None:
    repo = Repository(f"file://{tmp_path / 'disparu.git'}", "x", "disparu")

    with pytest.raises(RepositoryAccessError):
        await open_work_branch(repo, TOKEN, "atelier", AUTHOR)


def test_forge_files_alone_make_a_blank_repository() -> None:
    assert is_blank(["README.md", ".gitignore", ".github/workflows/ci.yml"])
    assert not is_blank(["README.md", "manifest.json"])
