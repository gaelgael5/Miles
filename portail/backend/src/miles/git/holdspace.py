from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from miles_socle.git.access import GitAccess
from miles_socle.git.failures import classify
from miles_socle.git.forge import Repository

from miles.git.workcopy import (
    BranchMissingError,
    BranchMovedError,
    WorkCopy,
    author_parts,
    remote_head,
    tracked_sha,
)
from miles.git.workdirs import SEGMENT_RE
from miles.git.worktree import RepositoryAccessError, work_branch_name

_REMOTE = "origin"
# Sous-répertoire des espaces de prise de main, sur le volume des copies de travail.
HOLDS_DIR = "_tenues"


@dataclass
class HeldCopy(WorkCopy):
    """La copie de la personne qui a la main : ses commits y restent jusqu'à publication.

    `signature` : « Nom <e-mail> » de son compte de forge, auteur ET committer de chaque
    commit (story 9def0adc, critère 6). `published` : la dernière tête publiée.
    """

    signature: str = ""
    published: str = ""

    async def commit_local(self, message: str) -> str:
        """Commit sans push ; rend son identifiant."""
        name, email = author_parts(self.signature)
        await self.git("add", "-A")
        # Les -c passés ici viennent après ceux du lanceur : le committer est la personne,
        # pas le compte technique de Miles — dans la forge, tout est à son nom.
        committed = await self.git(
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email}",
            "commit",
            "-q",
            f"--author={self.signature}",
            "-m",
            message,
        )
        if not committed.ok:
            raise RepositoryAccessError(classify(committed))
        self.head = (await self.git("rev-parse", "HEAD")).stdout.strip()
        return self.head

    async def unpublished(self) -> int:
        """Nombre de commits locaux que la forge n'a pas encore."""
        counted = await self.git("rev-list", "--count", f"{self.published}..HEAD")
        if not counted.ok:
            raise RepositoryAccessError(classify(counted))
        return int(counted.stdout.strip() or "0")

    async def publish(self) -> str:
        """Pousse les commits locaux ; rend la nouvelle tête publiée.

        Bail sur la dernière tête publiée : si la branche a bougé dans la forge, rien n'est
        écrasé et les commits locaux restent (critère 8).
        """
        if self.head == self.published:
            return self.head
        ref = f"refs/heads/{self.branch}"
        pushed = await self.git(
            "push", "-q", f"--force-with-lease={ref}:{self.published}", self.repo.url, f"HEAD:{ref}"
        )
        if not pushed.ok:
            if "stale info" in pushed.stderr or "rejected" in pushed.stderr:
                raise BranchMovedError(self.branch)
            raise RepositoryAccessError(classify(pushed))
        self.published = self.head
        return self.head


@dataclass
class HoldSpaces:
    """Un espace git par branche tenue, sur le volume des copies de travail (9def0adc).

    À l'inverse des copies de lecture (`WorkDirs`), l'espace n'est JAMAIS ramené sur la
    forge : il porte les commits non publiés, qui n'existent que là. Un geste interrompu
    n'y laisse que des modifications non commitées, effacées au geste suivant.
    """

    root: Path
    # Un geste à la fois par espace, comme pour les copies de lecture.
    _locks: dict[Path, asyncio.Lock] = field(default_factory=dict)

    def directory(self, workspace_id: str, slug: str) -> Path:
        if not (SEGMENT_RE.match(workspace_id) and SEGMENT_RE.match(slug)):
            raise ValueError("segment d'espace de prise de main invalide")
        target = (self.root / workspace_id / slug).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("espace de prise de main hors du volume")
        return target

    @asynccontextmanager
    async def open(
        self,
        repo: Repository,
        access: GitAccess,
        workspace_id: str,
        slug: str,
        *,
        published: str,
        signature: str,
    ) -> AsyncIterator[HeldCopy]:
        directory = self.directory(workspace_id, slug)
        lock = self._locks.setdefault(directory, asyncio.Lock())
        async with lock:
            copy = HeldCopy(repo, access, work_branch_name(workspace_id, slug), directory)
            copy.signature, copy.published = signature, published
            if (directory / ".git").is_dir():
                await _tidy(copy)
                await _follow(copy)
            else:
                # Espace absent (volume vidé, prise interrompue avant le clone) : il se
                # recrée depuis la forge. Rien ne s'y perd qui n'était déjà perdu, et ce
                # qu'on vient de cloner est publié par définition.
                await _clone(copy)
                copy.published = await _rev(copy, "HEAD")
            copy.head = await _rev(copy, "HEAD")
            yield copy

    async def forget(self, workspace_id: str) -> None:
        """Retire les espaces de prise de main de ce workspace.

        Appelé après la suppression du workspace, qui refuse tant qu'une branche est
        tenue : ce qui reste ici est donc publié ou rangé sur la forge.
        """
        if not SEGMENT_RE.match(workspace_id):
            raise ValueError("segment d'espace de prise de main invalide")
        target = (self.root / workspace_id).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("espace de prise de main hors du volume")
        await asyncio.to_thread(shutil.rmtree, target, True)

    async def discard(self, workspace_id: str, slug: str) -> None:
        directory = self.directory(workspace_id, slug)
        async with self._locks.setdefault(directory, asyncio.Lock()):
            await asyncio.to_thread(shutil.rmtree, directory, True)


async def _clone(copy: HeldCopy) -> None:
    ref = f"refs/heads/{copy.branch}"
    await asyncio.to_thread(copy.root.mkdir, parents=True, exist_ok=True)
    # La branche doit exister dans la forge : on ne la recrée jamais implicitement.
    await _remote_branch_head(copy)
    for args in (
        ("init", "-q"),
        ("remote", "add", _REMOTE, copy.repo.url),
        ("fetch", "-q", "--depth", "1", _REMOTE, f"+{ref}:refs/remotes/{_REMOTE}/{copy.branch}"),
        ("checkout", "-q", "-B", copy.branch, f"refs/remotes/{_REMOTE}/{copy.branch}"),
    ):
        done = await copy.git(*args)
        if not done.ok:
            raise RepositoryAccessError(classify(done))


async def _follow(copy: HeldCopy) -> None:
    """Sans commit en attente, l'espace se recale sur la forge.

    Une modification faite dans la forge pendant la prise doit être vue : sinon une
    version figerait une tête périmée, et les modifications suivantes partiraient d'elle.
    Avec des commits en attente, rien ne bouge : leur publication sera refusée si la
    branche a avancé (critère 8), plutôt que de les rejouer en silence sur autre chose.
    """
    if await _rev(copy, "HEAD") != copy.published:
        return
    tracking = f"refs/remotes/{_REMOTE}/{copy.branch}"
    ref = f"refs/heads/{copy.branch}"
    # Une branche supprimée dans la forge se dit comme telle, pas comme un dépôt muet.
    distant = await _remote_branch_head(copy)
    # UNE interrogation de la forge au lieu de deux, comme sur le chemin de la copie
    # partagée (enabler 782ce1e9, qui avait oublié celui-ci — bug 347ffd22) : le
    # `ls-remote` ci-dessus a DÉJÀ rendu le SHA distant, et récupérer ensuite des objets
    # qu'on tient déjà est un aller-retour HTTPS pur. Mesuré le 15/11/2026 sur
    # host-test-37, contre GitHub : `fetch --depth 1` ≈ 0,66 s, et une page du portail
    # ouvre la branche tenue 9 fois, gestes sérialisés par le verrou de la copie.
    #
    # CE N'EST PAS UN CACHE : la forge reste interrogée à chaque geste, donc une
    # modification faite dans GitHub pendant la prise est toujours vue — c'est la raison
    # d'être de `_follow`. Ni fenêtre de fraîcheur, ni délai, ni état gardé : on
    # n'économise que le transfert d'objets déjà présents, ce que le SHA prouve.
    if distant != await tracked_sha(copy, tracking):
        fetched = await copy.git("fetch", "-q", "--depth", "1", _REMOTE, f"+{ref}:{tracking}")
        if not fetched.ok:
            raise RepositoryAccessError(classify(fetched))
    remote = await _rev(copy, tracking)
    if remote != copy.published:
        moved = await copy.git("checkout", "-q", "-B", copy.branch, tracking)
        if not moved.ok:
            raise RepositoryAccessError(classify(moved))
        copy.published = remote


async def _remote_branch_head(copy: HeldCopy) -> str:
    """Rend la tête de la branche sur la forge ; refuse si elle n'y est plus.

    Le `ls-remote` est conservé alors que le `fetch` qui le suivait est devenu
    conditionnel : c'est lui qui fait que la forge est toujours interrogée, et lui seul
    qui distingue « branche supprimée » de « dépôt injoignable ».
    """
    ref = f"refs/heads/{copy.branch}"
    listed = await copy.git("ls-remote", "--heads", copy.repo.url, ref)
    if not listed.ok:
        raise RepositoryAccessError(classify(listed))
    head = remote_head(listed.stdout, ref)
    if head is None:
        raise BranchMissingError(copy.branch)
    return head


async def _rev(copy: HeldCopy, ref: str) -> str:
    resolved = await copy.git("rev-parse", ref)
    if not resolved.ok:
        raise RepositoryAccessError(classify(resolved))
    return resolved.stdout.strip()


async def _tidy(copy: HeldCopy) -> None:
    # Les commits restent ; seules les modifications d'un geste interrompu partent.
    for args in (("reset", "-q", "--hard", "HEAD"), ("clean", "-q", "-fdx")):
        done = await copy.git(*args)
        if not done.ok:
            raise RepositoryAccessError(classify(done))
