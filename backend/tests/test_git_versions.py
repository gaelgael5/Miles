from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from miles.datamodels.grammar import Problem
from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.versions import (
    VersionTakenError,
    fetch_versions,
    restore_tree,
    same_tree,
    tag_head,
)
from miles.git.workcopy import checkout
from miles.secrets.model import Secret
from miles.workshop.validation import FileReport, validate_branch

TOKEN = GitAccess(token=Secret("jeton-local"))
AUTHOR = "alice via Miles <alice@annuaire.miles.invalid>"
BRANCH = "work/atelier"
MANIFEST = json.dumps({"format_version": 1, "min_app_version": None, "capabilities": []})
PERSONNE = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n"


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _repo(tmp_path: Path, files: dict[str, str]) -> Repository:
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(seed))
    for path, content in {"manifest.json": MANIFEST, **files}.items():
        (seed / path).parent.mkdir(parents=True, exist_ok=True)
        (seed / path).write_text(content)
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *identity, "commit", "-q", "-m", "base")
    _git("-C", str(seed), "push", "-q", str(bare), f"main:{BRANCH}")
    return Repository(f"file://{bare}", "local", "remote")


async def test_version_is_an_annotated_tag_signed_by_the_person(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})

    async with checkout(repo, TOKEN, BRANCH) as copy:
        await tag_head(copy, 1, "Première recette", AUTHOR)
        head = copy.head
    async with checkout(repo, TOKEN, BRANCH) as copy:
        [version] = await fetch_versions(copy)

    assert (version.number, version.label, version.commit) == (1, "Première recette", head)
    assert version.author == "alice via Miles <alice@annuaire.miles.invalid>"


async def test_version_names_its_branch_and_an_older_tag_names_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})
    bare = repo.url.removeprefix("file://")
    _git("-C", bare, "branch", "work/essai", BRANCH)
    # Étiquette posée avant les branches filles : sans ligne de pied « Branche ».
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    _git("-C", bare, *identity, "tag", "-a", "version/1", BRANCH, "-m", "Ancienne")

    async with checkout(repo, TOKEN, "work/essai") as copy:
        await tag_head(copy, 2, "Depuis la branche", AUTHOR)
    async with checkout(repo, TOKEN, BRANCH) as copy:
        versions = await fetch_versions(copy)

    assert [(v.number, v.label, v.branch) for v in versions] == [
        (2, "Depuis la branche", "work/essai"),
        (1, "Ancienne", None),
    ]


async def test_versions_are_listed_newest_first_ignoring_foreign_tags(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {})
    bare = repo.url.removeprefix("file://")
    _git("--git-dir", bare, "tag", "version/9", BRANCH)  # légère : pas une version Miles
    _git("--git-dir", bare, "tag", "release-1", BRANCH)

    async with checkout(repo, TOKEN, BRANCH) as copy:
        await tag_head(copy, 1, "un", AUTHOR)
        await tag_head(copy, 2, "deux", AUTHOR)
        versions = await fetch_versions(copy)

    assert [v.number for v in versions] == [2, 1]


async def test_empty_repository_has_no_version(tmp_path: Path) -> None:
    async with checkout(_repo(tmp_path, {}), TOKEN, BRANCH) as copy:
        assert await fetch_versions(copy) == []


async def test_number_taken_meanwhile_is_refused_without_moving_the_other(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, {})

    async with checkout(repo, TOKEN, BRANCH) as first, checkout(repo, TOKEN, BRANCH) as second:
        await tag_head(second, 1, "gagnante", AUTHOR)
        with pytest.raises(VersionTakenError):
            await tag_head(first, 1, "perdante", AUTHOR)
    async with checkout(repo, TOKEN, BRANCH) as copy:
        [kept] = await fetch_versions(copy)

    assert kept.label == "gagnante"


async def test_restoring_brings_back_the_old_tree_without_rewriting_history(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, {"shared/messages/personne.yaml": PERSONNE})
    async with checkout(repo, TOKEN, BRANCH) as copy:
        await tag_head(copy, 1, "un", AUTHOR)
        await copy.write("shared/messages/colis.yaml", "nom: colis")
        await copy.remove("shared/messages/personne.yaml")
        await copy.commit_push("Changement", AUTHOR)

    async with checkout(repo, TOKEN, BRANCH) as copy:
        [version] = await fetch_versions(copy)
        assert not await same_tree(copy, version.commit)
        await restore_tree(copy, version.commit)
        await copy.commit_push("Retour", AUTHOR)
    async with checkout(repo, TOKEN, BRANCH) as copy:
        [version] = await fetch_versions(copy)
        restored = await same_tree(copy, version.commit)
        paths = await copy.paths()

    assert restored
    assert paths == ["manifest.json", "shared/messages/personne.yaml"]
    bare = repo.url.removeprefix("file://")
    assert _git("--git-dir", bare, "rev-list", "--count", BRANCH).strip() == "3"


async def test_valid_configuration_has_no_report(tmp_path: Path) -> None:
    async with checkout(
        _repo(tmp_path, {"shared/messages/personne.yaml": PERSONNE}), TOKEN, BRANCH
    ) as copy:
        assert await validate_branch(copy) == []


async def test_every_faulty_file_is_reported(tmp_path: Path) -> None:
    files = {
        "prod/x.json": "{}",
        "shared/messages/colis.yaml": "nom: colis\nversion: 1\nproprietes:\n  d:\n    type: objet\n"
        "    modele: personne\n",
        "domains/suivi/messages/lot.yaml": PERSONNE.replace("nom: personne", "nom: autre"),
        "shared/messages/casse.yaml": "nom: [\n",
    }
    async with checkout(_repo(tmp_path, files), TOKEN, BRANCH) as copy:
        reports = await validate_branch(copy)

    assert reports == [
        FileReport("", (Problem("prod", "dossier_d_environnement"),)),
        FileReport(
            "domains/suivi/messages/lot.yaml", (Problem("nom", "nom_different_du_fichier", "lot"),)
        ),
        FileReport(
            "shared/messages/casse.yaml", (Problem("", "yaml_invalide", "ligne 2, colonne 1"),)
        ),
        FileReport(
            "shared/messages/colis.yaml",
            (Problem("proprietes.d.modele", "modele_inconnu", "personne"),),
        ),
    ]
