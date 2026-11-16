"""Les lectures d'une branche se recouvrent, et aucune n'attend (enabler 7fb3577c).

Avant, toute ouverture posait un arbre de travail — `checkout -f`, `clean -fdx` — même en
lecture, ce qui obligeait à sérialiser les gestes par un verrou : une page du portail
payait la SOMME de ses neuf lectures (21 s mesurées le 15/11/2026) au lieu de la plus
longue.

Ce que ces tests tiennent est l'arbitrage de Gael du 15/11/2026 : aucune lecture n'attend
jamais, et une lecture concurrente d'une écriture rend l'état cohérent d'AVANT celle-ci.
Les attentes ne sont pas chronométrées mais prouvées par des jalons : un test au
chronomètre reste vert sous charge, et rouge sans raison un jour de machine occupée.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from miles_socle.git.access import GitAccess
from miles_socle.git.forge import Repository
from miles_socle.secrets.model import Secret

from miles.git.holdspace import HoldSpaces
from miles.git.workcopy import BranchMissingError, ReadOnlyCopyError
from miles.git.workdirs import WorkDirs

TOKEN = GitAccess(token=Secret("jeton-local"))
AUTHOR = "alice via Miles <alice@annuaire.miles.invalid>"
LEA = "Léa Martin <lea@forge.invalid>"
BRANCH = "back/retrait/atelier"
HELD_BRANCH = "back/retrait/edition"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]
# Un geste qui attendrait un verrou bloquerait pour toujours : on borne, et le dépassement
# EST le défaut qu'on cherche.
DELAI = 10


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return out.stdout


def _remote(tmp_path: Path, branch: str = BRANCH) -> tuple[Repository, Path, str]:
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(seed))
    (seed / "a.yaml").write_text("un\n")
    (seed / "domains").mkdir()
    (seed / "domains" / "b.yaml").write_text("deux\n")
    _git("-C", str(seed), "add", "-A")
    _git("-C", str(seed), *IDENTITY, "commit", "-q", "-m", "base")
    _git("-C", str(seed), "push", "-q", str(bare), f"main:{branch}")
    head = _git("-C", str(seed), "rev-parse", "HEAD").strip()
    return Repository(f"file://{bare}", "local", "remote"), seed, head


def _push_outside(seed: Path, repo: Repository, content: str, branch: str = BRANCH) -> str:
    (seed / "a.yaml").write_text(content)
    _git("-C", str(seed), *IDENTITY, "commit", "-qam", "hors Miles")
    _git("-C", str(seed), "push", "-q", repo.url.removeprefix("file://"), f"main:{branch}")
    return _git("-C", str(seed), "rev-parse", "HEAD").strip()


async def test_a_read_serves_the_whole_tree_of_the_published_head(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        assert await copy.paths() == ["a.yaml", "domains/b.yaml"]
        assert (await copy.read("a.yaml"), await copy.read("domains/b.yaml")) == ("un\n", "deux\n")
        assert await copy.read("absent.yaml") is None
        assert copy.head == head


async def test_a_first_read_on_an_empty_volume_still_serves_the_branch(tmp_path: Path) -> None:
    """Sans copie persistante, il n'y a rien de local : la lecture récupère et sert."""
    repo, _, head = _remote(tmp_path)

    async with WorkDirs(tmp_path / "neuf").read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        assert (await copy.read("a.yaml"), copy.head) == ("un\n", head)


async def test_a_read_follows_a_change_made_in_the_forge(tmp_path: Path) -> None:
    """« Git fait foi » : la forge est interrogée à chaque geste, sans cache ni délai."""
    repo, seed, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")
    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        premier = await copy.read("a.yaml")
    bougee = _push_outside(seed, repo, "deux\n")

    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        assert (premier, await copy.read("a.yaml"), copy.head) == ("un\n", "deux\n", bougee)


async def test_a_read_view_refuses_to_be_written(tmp_path: Path) -> None:
    """Une vue de lecture qui accepterait d'écrire écrirait dans un répertoire jetable."""
    repo, _, _ = _remote(tmp_path)

    async with WorkDirs(tmp_path / "volume").read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        with pytest.raises(ReadOnlyCopyError):
            await copy.write("a.yaml", "jamais\n")
        with pytest.raises(ReadOnlyCopyError):
            await copy.commit_push("jamais", AUTHOR)


async def test_two_reads_of_the_same_branch_overlap_instead_of_queueing(tmp_path: Path) -> None:
    """Le critère 2 : les gestes se recouvrent, au lieu de faire la queue.

    Chaque lecture annonce son entrée et n'en sort qu'une fois l'autre entrée : sous un
    verrou partagé, la seconde n'entrerait jamais et l'attente bornée rougirait. C'est le
    recouvrement qu'on prouve, pas une durée.
    """
    repo, _, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")
    dedans, les_deux = 0, asyncio.Event()

    async def lire() -> str | None:
        nonlocal dedans
        async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
            dedans += 1
            if dedans == 2:
                les_deux.set()
            # Aucune des deux ne sort avant que l'autre soit entrée : sous un verrou
            # partagé, la première attendrait ici pour toujours.
            await asyncio.wait_for(les_deux.wait(), DELAI)
            return await copy.read("a.yaml")

    contenus = await asyncio.wait_for(asyncio.gather(lire(), lire()), DELAI * 2)

    assert (contenus, dedans) == (["un\n", "un\n"], 2)


async def test_a_read_keeps_its_complete_tree_while_a_write_mutates_the_shared_copy(
    tmp_path: Path,
) -> None:
    """Le critère 3 : aucune lecture ne voit un arbre à moitié nettoyé.

    L'écriture, qui `checkout -f` et `clean -fdx` dans la copie partagée, se déroule
    ENTIÈREMENT pendant que la lecture est ouverte. Avec un arbre partagé — ce que
    rétablirait un `clean -fdx` sur le chemin de lecture — ou avec un verrou commun, elle
    ne pourrait pas : la lecture rendrait un arbre amputé, ou l'écriture attendrait.
    """
    repo, _, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async def ecrire() -> None:
        async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as ecriture:
            await ecriture.write("a.yaml", "écrit pendant la lecture\n")
            await ecriture.write("orphelin.yaml", "x\n")

    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as lecture:
        # Bornée : si la lecture et l'écriture partageaient le verrou, l'écriture
        # n'entrerait jamais et ce test rougirait au lieu de se bloquer.
        await asyncio.wait_for(ecrire(), DELAI)
        ecriture_terminee = True
        chemins = await lecture.paths()
        contenus = [await lecture.read(p) for p in chemins]

    assert ecriture_terminee
    assert chemins == ["a.yaml", "domains/b.yaml"]
    assert contenus == ["un\n", "deux\n"]


async def test_a_read_launched_during_a_write_does_not_wait_for_it(tmp_path: Path) -> None:
    """Le critère 4 : la lecture rend l'état d'avant, et elle le rend sans attendre.

    L'écriture tient le verrou de l'arbre jusqu'à ce que la lecture ait fini : si la
    lecture attendait ce verrou, les deux s'attendraient et l'attente bornée rougirait.
    Rien n'est chronométré — c'est l'ordre des jalons qui porte la preuve.

    La copie est chaude, comme elle l'est en service : une lecture n'attend un transfert
    que lorsque la branche a bougé sur la forge, et jamais l'écriture entière.
    """
    repo, _, _ = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")
    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH):
        pass
    lecture_finie, ecriture_finie = asyncio.Event(), asyncio.Event()

    async def ecrire() -> None:
        async with dirs.checkout(repo, TOKEN, "retrait", BRANCH) as copy:
            await copy.write("a.yaml", "pendant\n")
            await asyncio.wait_for(lecture_finie.wait(), DELAI)
            await copy.commit_push("Écriture", AUTHOR)
        ecriture_finie.set()

    async def lire() -> tuple[str | None, bool]:
        async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
            contenu = await copy.read("a.yaml")
        pendant_l_ecriture = not ecriture_finie.is_set()
        lecture_finie.set()
        return contenu, pendant_l_ecriture

    _, lu = await asyncio.wait_for(asyncio.gather(ecrire(), lire()), DELAI * 2)

    assert lu == ("un\n", True)


async def test_replaying_a_read_gives_what_two_concurrent_reads_give(tmp_path: Path) -> None:
    """Le critère 7 : à la suite ou en même temps, le geste rend la même chose."""
    repo, _, head = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")

    async def lire() -> tuple[str | None, str]:
        async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
            return await copy.read("a.yaml"), copy.head

    ensemble = await asyncio.gather(lire(), lire())
    suite = [await lire(), await lire()]

    assert ensemble == suite == [("un\n", head)] * 2


async def test_a_branch_deleted_on_the_forge_is_named_as_missing_on_a_read(
    tmp_path: Path,
) -> None:
    """Le critère 6 : « branche introuvable », jamais « dépôt injoignable »."""
    repo, _, head = _remote(tmp_path)
    dirs = WorkDirs(tmp_path / "volume")
    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH):
        pass
    _git("-C", repo.url.removeprefix("file://"), "branch", "-D", BRANCH)

    with pytest.raises(BranchMissingError):
        async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH):
            pass

    # Et le geste suivant, une fois la branche revenue, repart sans rien à rattraper.
    _git("-C", repo.url.removeprefix("file://"), "branch", BRANCH, head)
    async with dirs.read_tree(repo, TOKEN, "retrait", BRANCH) as copy:
        assert await copy.read("a.yaml") == "un\n"


async def _tenir(spaces: HoldSpaces, repo: Repository, head: str, contenu: str) -> str:
    async with spaces.open(
        repo, TOKEN, "retrait", "edition", published=head, signature=LEA
    ) as copy:
        await copy.write("a.yaml", contenu)
        return await copy.commit_local("modification")


async def test_the_holder_reads_their_unpublished_commits(tmp_path: Path) -> None:
    """Le critère 5 : un commit local n'est visible que de qui l'a fait (9def0adc)."""
    repo, _, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _tenir(spaces, repo, head, "à moi\n")

    async with spaces.read_tree(
        repo, TOKEN, "retrait", "edition", published=head, signature=LEA
    ) as copy:
        assert (await copy.read("a.yaml"), copy.head) == ("à moi\n", mine)
        assert await copy.unpublished() == 1
    async with WorkDirs(tmp_path / "volume").read_tree(
        repo, TOKEN, "retrait", HELD_BRANCH
    ) as autre:
        assert (await autre.read("a.yaml"), autre.head) == ("un\n", head)


async def test_without_pending_work_the_holder_reads_the_forge(tmp_path: Path) -> None:
    repo, seed, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    bougee = _push_outside(seed, repo, "hors Miles\n", HELD_BRANCH)

    async with spaces.read_tree(
        repo, TOKEN, "retrait", "edition", published=head, signature=LEA
    ) as copy:
        assert (await copy.read("a.yaml"), copy.head) == ("hors Miles\n", bougee)


async def test_a_read_never_moves_the_held_space(tmp_path: Path) -> None:
    """Une lecture ne déplace pas le travail de quelqu'un : l'espace reste où il était."""
    repo, seed, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")
    mine = await _tenir(spaces, repo, head, "à moi\n")
    _push_outside(seed, repo, "hors Miles\n", HELD_BRANCH)

    async with spaces.read_tree(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    espace = spaces.directory("retrait", "edition")

    assert _git("-C", str(espace), "rev-parse", "HEAD").strip() == mine
    assert (espace / "a.yaml").read_text() == "à moi\n"


async def test_two_reads_of_a_held_branch_overlap(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")
    await _tenir(spaces, repo, head, "à moi\n")
    dedans, les_deux = 0, asyncio.Event()

    async def lire() -> str | None:
        nonlocal dedans
        async with spaces.read_tree(
            repo, TOKEN, "retrait", "edition", published=head, signature=LEA
        ) as copy:
            dedans += 1
            if dedans == 2:
                les_deux.set()
            await asyncio.wait_for(les_deux.wait(), DELAI)
            return await copy.read("a.yaml")

    assert await asyncio.wait_for(asyncio.gather(lire(), lire()), DELAI * 2) == ["à moi\n"] * 2


async def test_a_read_of_a_held_branch_does_not_wait_for_a_write(tmp_path: Path) -> None:
    """L'espace existe déjà : son premier clone est le seul geste de lecture qui attende."""
    repo, _, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")
    async with spaces.open(repo, TOKEN, "retrait", "edition", published=head, signature=LEA):
        pass
    lecture_finie, ecriture_finie = asyncio.Event(), asyncio.Event()

    async def ecrire() -> None:
        async with spaces.open(
            repo, TOKEN, "retrait", "edition", published=head, signature=LEA
        ) as copy:
            await copy.write("a.yaml", "pendant\n")
            await asyncio.wait_for(lecture_finie.wait(), DELAI)
            await copy.commit_local("modification")
        ecriture_finie.set()

    async def lire() -> tuple[str | None, bool]:
        async with spaces.read_tree(
            repo, TOKEN, "retrait", "edition", published=head, signature=LEA
        ) as copy:
            contenu = await copy.read("a.yaml")
        pendant = not ecriture_finie.is_set()
        lecture_finie.set()
        return contenu, pendant

    _, lu = await asyncio.wait_for(asyncio.gather(ecrire(), lire()), DELAI * 2)

    assert lu == ("un\n", True)


async def test_a_held_read_refuses_to_commit_or_publish(tmp_path: Path) -> None:
    repo, _, head = _remote(tmp_path, HELD_BRANCH)
    spaces = HoldSpaces(tmp_path / "tenues")

    async with spaces.read_tree(
        repo, TOKEN, "retrait", "edition", published=head, signature=LEA
    ) as copy:
        with pytest.raises(ReadOnlyCopyError):
            await copy.commit_local("jamais")
        with pytest.raises(ReadOnlyCopyError):
            await copy.publish()
