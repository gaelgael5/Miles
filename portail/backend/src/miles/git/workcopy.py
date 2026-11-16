from __future__ import annotations

import asyncio
import re
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from miles_socle.git.access import GitAccess
from miles_socle.git.failures import classify
from miles_socle.git.forge import Repository
from miles_socle.git.runner import GitResult, run_git

from miles.git.worktree import RepositoryAccessError, WorkBranchError

_REMOTE = "origin"
_AUTHOR_RE = re.compile(r"^(?P<name>[^<>]+) <(?P<email>[^<>]+)>$")


def author_parts(author: str) -> tuple[str, str]:
    """(nom, e-mail) d'un auteur git « Nom <e-mail> » ; refus s'il est mal formé."""
    match = _AUTHOR_RE.match(author)
    if match is None:
        raise ValueError("auteur de commit mal formé")
    return match["name"], match["email"]


class BranchMissingError(WorkBranchError):
    """La branche n'existe pas sur la forge : on ne la recrée jamais implicitement."""


class BranchMovedError(WorkBranchError):
    """La branche a bougé pendant l'écriture : rien n'est poussé, l'appelant réessaie."""


def remote_head(stdout: str, ref: str) -> str | None:
    """Le SHA que `ls-remote` a rendu pour cette référence, sans relancer git."""
    for line in stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == ref:
            return sha.strip() or None
    return None


@dataclass
class WorkCopy:
    """Copie locale jetable d'UNE branche, le temps d'un geste de lecture ou d'écriture.

    Rien n'est gardé entre deux gestes, ni en base ni en mémoire : git reste la seule
    source de vérité du paramétrage (cadrage, « Décisions d'architecture »).
    """

    repo: Repository
    access: GitAccess
    branch: str
    root: Path
    head: str = ""

    @property
    def git_root(self) -> Path:
        """Le répertoire où git est lancé. Distinct de `root` pour une vue en lecture."""
        return self.root

    async def git(self, *args: str) -> GitResult:
        return await run_git(list(args), self.git_root, self.access)

    async def paths(self) -> list[str]:
        # Filtrés par l'appelant : dans un pathspec git, `*` traverse les `/`.
        listed = await self.git("ls-files", "-z")
        return sorted(p for p in listed.stdout.split("\0") if p)

    async def read(self, path: str) -> str | None:
        return await asyncio.to_thread(_read, self._inside(path))

    async def write(self, path: str, content: str) -> None:
        await asyncio.to_thread(_write, self._inside(path), content)

    async def remove(self, path: str) -> None:
        await self.git("rm", "-q", "--", path)

    async def commit_push(self, message: str, author: str) -> str:
        """Commit et push ; rend l'identifiant du commit. Refuse si la branche a bougé."""
        await self.git("add", "-A")
        committed = await self.git("commit", "-q", f"--author={author}", "-m", message)
        if not committed.ok:
            raise RepositoryAccessError(classify(committed))
        sha = (await self.git("rev-parse", "HEAD")).stdout.strip()
        ref = f"refs/heads/{self.branch}"
        # Bail sur la tête lue au départ : si la branche a été supprimée ou a avancé
        # entre-temps, le push échoue au lieu de la recréer ou d'écraser l'autre écriture.
        pushed = await self.git(
            "push", "-q", f"--force-with-lease={ref}:{self.head}", self.repo.url, f"HEAD:{ref}"
        )
        if not pushed.ok:
            if "stale info" in pushed.stderr or "rejected" in pushed.stderr:
                raise BranchMovedError(self.branch)
            raise RepositoryAccessError(classify(pushed))
        return sha

    def _inside(self, path: str) -> Path:
        # Les chemins viennent de noms validés ; la garde reste, au cas où une évolution
        # laisserait passer un `..` : on n'écrit jamais hors de la copie.
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("chemin hors de la copie de travail")
        return target


async def tracked_sha(copy: WorkCopy, tracking: str) -> str | None:
    """Le SHA que la copie tient déjà pour cette branche, ou None.

    Jamais une erreur : une copie neuve n'a pas encore de référence de suivi, et c'est le
    cas NORMAL du premier passage. Rendre None fait alors différer la comparaison, donc
    récupérer — l'économie ne se décide que sur une égalité prouvée, jamais sur un doute.

    Posées ici avec `remote_head`, et non dans l'un des deux chemins d'ouverture : la même
    règle écrite deux fois n'a valu que dans un seul (bug 347ffd22, où le chemin de la
    branche tenue avait été oublié).
    """
    result = await copy.git("rev-parse", "--verify", "--quiet", tracking)
    return result.stdout.strip() or None if result.ok else None


# --- Lecture d'un commit, sans toucher à l'arbre partagé (enabler 7fb3577c) -------------
#
# Toute ouverture de copie MUTAIT l'arbre (`checkout -f`, `clean -fdx`), même en lecture :
# il fallait donc un verrou par répertoire, et une page du portail payait la SOMME de ses
# neuf lectures au lieu de la plus longue — 21 s mesurées le 15/11/2026 sur host-test-37.
# Une lecture n'a aucune raison de muter quoi que ce soit, et c'est parce qu'elle mutait
# qu'il fallait la sérialiser.
#
# Les fichiers du commit sont donc posés dans un répertoire PROPRE À CE GESTE, et le
# verrou de l'arbre partagé ne concerne plus que les écritures. Ce n'est pas un cache : le
# répertoire naît du SHA que la forge vient de rendre, et meurt avec le geste — ni fenêtre
# de fraîcheur, ni délai, ni état gardé. Et la lecture reste une lecture de FICHIERS, octet
# pour octet celle d'avant : ce qui est admis ou refusé ne change pas.


class ReadOnlyCopyError(TypeError):
    """On a tenté d'écrire dans une vue de lecture : c'est une faute de programme."""


@dataclass
class CommitView(WorkCopy):
    """Vue en lecture d'un commit : les fichiers à part, git dans le dépôt partagé."""

    # Le dépôt où git tourne — celui de la copie persistante, qui porte les objets.
    repo_dir: Path = Path()
    # Sérialise les `fetch` lancés depuis une lecture. Voir `git` ci-dessous.
    fetch_lock: asyncio.Lock | None = None

    @property
    def git_root(self) -> Path:
        return self.repo_dir

    async def git(self, *args: str) -> GitResult:
        # Un `fetch` est la seule plomberie MUTANTE qu'une lecture lance encore — ici
        # celui des étiquettes de version, et dans `published_head` celui des objets de la
        # branche. Il écrit des références, et deux fetch concurrents dans le même dépôt se
        # disputent le verrou de référence de git : l'un échoue sur « cannot lock ref ». Le
        # reste (ls-tree, archive, rev-parse) ne lit que des objets et ne craint aucune
        # concurrence, pas même celle d'une écriture qui recale l'arbre à côté.
        if args and args[0] == "fetch" and self.fetch_lock is not None:
            async with self.fetch_lock:
                return await super().git(*args)
        return await super().git(*args)

    async def paths(self) -> list[str]:
        # `ls-files` lirait l'INDEX du dépôt partagé, qui n'est pas ce qu'on sert — et que
        # l'écriture d'à côté est en train de changer. Les chemins viennent de l'arbre du
        # commit servi, comme son contenu.
        listed = await self.git("ls-tree", "-r", "--name-only", "-z", self.head)
        return sorted(p for p in listed.stdout.split("\0") if p)

    async def write(self, path: str, content: str) -> None:
        raise ReadOnlyCopyError("une vue de lecture ne s'écrit pas")

    async def remove(self, path: str) -> None:
        raise ReadOnlyCopyError("une vue de lecture ne s'écrit pas")

    async def commit_push(self, message: str, author: str) -> str:
        raise ReadOnlyCopyError("une vue de lecture ne commite pas")


@dataclass
class TreeCopy(CommitView):
    """La tête publiée d'une branche, lue sans poser d'arbre dans la copie partagée."""


async def ensure_repo(copy: WorkCopy) -> None:
    """Le dépôt local existe et désigne la bonne adresse, sans toucher à l'arbre.

    L'adresse est reposée à chaque geste : le dépôt d'un workspace peut changer, et le
    jeton ne s'y écrit jamais (il passe par l'assistant d'identifiants du lanceur).
    """
    await asyncio.to_thread(copy.git_root.mkdir, parents=True, exist_ok=True)
    if not (copy.git_root / ".git").is_dir():
        for args in (("init", "-q"), ("remote", "add", _REMOTE, copy.repo.url)):
            done = await copy.git(*args)
            if not done.ok:
                raise RepositoryAccessError(classify(done))
    reset = await copy.git("remote", "set-url", _REMOTE, copy.repo.url)
    if not reset.ok:
        raise RepositoryAccessError(classify(reset))


async def remote_branch_head(copy: WorkCopy) -> str:
    """Le SHA de la tête de la branche sur la forge ; refus nommé si elle n'y est plus.

    Interroger la forge à CHAQUE geste est ce qui tient « git fait foi » : une modification
    faite dans la forge est toujours vue. C'est aussi le seul endroit qui distingue
    « branche supprimée » de « dépôt injoignable ».
    """
    ref = f"refs/heads/{copy.branch}"
    listed = await copy.git("ls-remote", "--heads", copy.repo.url, ref)
    if not listed.ok:
        raise RepositoryAccessError(classify(listed))
    head = remote_head(listed.stdout, ref)
    if head is None:
        raise BranchMissingError(copy.branch)
    return head


async def transfer(copy: WorkCopy, *args: str) -> GitResult:
    """Lance git SANS repasser par la sérialisation des transferts de la vue de lecture.

    Réservé à qui tient déjà ce verrou : `CommitView.git` le reprend sur un `fetch`, et un
    `asyncio.Lock` n'est pas réentrant — le geste s'attendrait lui-même, jusqu'au délai de
    git. Mesuré en écrivant `published_head` : un `fetch` instantané devenait une minute.
    """
    return await run_git(list(args), copy.git_root, copy.access)


async def published_head(copy: WorkCopy, lock: asyncio.Lock) -> str:
    """Le SHA publié à servir, ses objets présents en local, sans poser d'arbre.

    Le verrou ne tient que le TRANSFERT, jamais la lecture : deux lectures qui découvrent
    la même avance de la branche ne la récupèrent qu'une fois, et celle qui attend n'attend
    que ce transfert-là. Quand il n'y a rien à récupérer — le cas ordinaire — aucune des
    deux ne prend le verrou.
    """
    # Le répertoire d'abord : c'est de LÀ que git est lancé, et un volume neuf ne le
    # porte pas encore. Créer un répertoire n'est pas muter un arbre.
    await asyncio.to_thread(copy.git_root.mkdir, parents=True, exist_ok=True)
    tracking = f"refs/remotes/{_REMOTE}/{copy.branch}"
    distant = await remote_branch_head(copy)
    if distant == await tracked_sha(copy, tracking):
        return distant
    async with lock:
        # Relu sous le verrou : la lecture qui attendait trouve le transfert déjà fait.
        if distant != await tracked_sha(copy, tracking):
            await ensure_repo(copy)
            ref = f"refs/heads/{copy.branch}"
            fetched = await transfer(
                copy, "fetch", "-q", "--depth", "1", _REMOTE, f"+{ref}:{tracking}"
            )
            if not fetched.ok:
                raise RepositoryAccessError(classify(fetched))
        # La branche a pu avancer entre le `ls-remote` et le transfert : on sert ce qui est
        # arrivé, qui est un état cohérent et plus récent, jamais un SHA qu'on n'a pas.
        return await tracked_sha(copy, tracking) or distant


@asynccontextmanager
async def tree_of[V: WorkCopy](view: V, sha: str) -> AsyncIterator[V]:
    """Les fichiers de `sha`, posés dans un répertoire propre à ce geste et détruits après.

    `git archive` écrit l'arbre du commit sans toucher ni l'index ni l'arbre de travail du
    dépôt partagé : c'est ce qui permet à deux lectures de la même branche de se recouvrir.
    """
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-tree-"))
    try:
        copy = replace(view, root=workdir / "files")
        copy.head = sha
        await asyncio.to_thread(copy.root.mkdir, parents=True, exist_ok=True)
        archive = workdir / "tree.tar"
        written = await copy.git("archive", "-o", str(archive), sha)
        if not written.ok:
            raise RepositoryAccessError(classify(written))
        await asyncio.to_thread(_untar, archive, copy.root)
        yield copy
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


def _untar(archive: Path, root: Path) -> None:
    with tarfile.open(archive) as tar:
        # `filter="data"` refuse tout chemin absolu, tout « .. » et tout nœud spécial : git
        # n'en produit pas, et ce n'est pas une raison pour déballer une archive sans garde.
        tar.extractall(root, filter="data")


@asynccontextmanager
async def checkout(repo: Repository, access: GitAccess, branch: str) -> AsyncIterator[WorkCopy]:
    """Clone superficiel de `branch`, détruit à la sortie quoi qu'il arrive."""
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-copy-"))
    try:
        listed = await run_git(
            ["ls-remote", "--heads", repo.url, f"refs/heads/{branch}"], workdir, access
        )
        if not listed.ok:
            raise RepositoryAccessError(classify(listed))
        if not listed.stdout.strip():
            raise BranchMissingError(branch)
        root = workdir / "copy"
        cloned = await run_git(
            ["clone", "-q", "--depth", "1", "--branch", branch, repo.url, str(root)],
            workdir,
            access,
        )
        if not cloned.ok:
            raise RepositoryAccessError(classify(cloned))
        copy = WorkCopy(repo, access, branch, root)
        copy.head = (await copy.git("rev-parse", "HEAD")).stdout.strip()
        yield copy
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


def _read(path: Path) -> str | None:
    try:
        # newline="" : sans conversion de fins de ligne, comme à l'écriture.
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" : le contenu est écrit tel que fourni, sans conversion de fins de ligne,
    # pour que la relecture rende exactement ce qui a été déposé (critère 2).
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
