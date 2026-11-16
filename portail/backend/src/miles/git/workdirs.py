from __future__ import annotations

import asyncio
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from miles_socle.git.access import GitAccess
from miles_socle.git.failures import classify
from miles_socle.git.forge import Repository
from miles_socle.git.runner import run_git

from miles.git.workcopy import BranchMissingError, WorkCopy, remote_head, tracked_sha
from miles.git.worktree import WORK_BRANCH_ROOT, RepositoryAccessError

# Segments de chemin : un identifiant de workspace et un nom de branche déjà validés par
# leurs propres règles. Revalidés ici parce qu'ils deviennent des chemins sur le volume.
SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_REMOTE = "origin"


@dataclass
class WorkDirs:
    """Une copie persistante par branche de travail, sur le volume monté (Gael, 22/10/2026).

    Git fait foi : chaque geste commence par ramener la copie sur la tête distante
    (fetch, reset, clean), si bien qu'une modification faite dans GitHub est vue, et
    qu'un geste interrompu ne laisse rien au suivant. Le répertoire n'est qu'un cache
    qui évite de recloner ; le supprimer ne perd rien.
    """

    root: Path
    # Un geste à la fois par répertoire : deux requêtes sur la même branche se
    # piétineraient l'arbre de travail. Le back-office tourne en un seul processus.
    _locks: dict[Path, asyncio.Lock] = field(default_factory=dict)

    def directory(self, workspace_id: str, branch: str) -> Path:
        if not SEGMENT_RE.match(workspace_id):
            raise ValueError("segment de copie de travail invalide")
        # On retire le préfixe DE CE workspace : une branche rangée sous un autre garde
        # ses barres, échoue au contrôle de segment, et n'atteint donc jamais le volume
        # d'un workspace qui n'est pas le sien.
        name = branch.removeprefix(f"{WORK_BRANCH_ROOT}{workspace_id}/")
        if not SEGMENT_RE.match(name):
            raise ValueError("segment de copie de travail invalide")
        target = (self.root / workspace_id / name).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("copie de travail hors du volume")
        return target

    async def forget(self, workspace_id: str) -> None:
        """Retire les copies persistantes de ce workspace du volume.

        Ce ne sont que des caches : git fait foi, et chaque geste repart de la tête
        distante. Les laisser après la suppression du workspace remplirait le volume de
        dossiers que plus rien ne nomme.
        """
        if not SEGMENT_RE.match(workspace_id):
            raise ValueError("segment de copie de travail invalide")
        target = (self.root / workspace_id).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("copie de travail hors du volume")
        await asyncio.to_thread(shutil.rmtree, target, True)

    @asynccontextmanager
    async def checkout(
        self, repo: Repository, access: GitAccess, workspace_id: str, branch: str
    ) -> AsyncIterator[WorkCopy]:
        directory = self.directory(workspace_id, branch)
        lock = self._locks.setdefault(directory, asyncio.Lock())
        async with lock:
            copy = WorkCopy(repo, access, branch, directory)
            await _align(copy)
            yield copy


async def _align(copy: WorkCopy) -> None:
    """Amène la copie exactement sur la tête distante de sa branche."""
    ref = f"refs/heads/{copy.branch}"
    await asyncio.to_thread(copy.root.mkdir, parents=True, exist_ok=True)
    listed = await run_git(["ls-remote", "--heads", copy.repo.url, ref], copy.root, copy.access)
    if not listed.ok:
        raise RepositoryAccessError(classify(listed))
    if not listed.stdout.strip():
        raise BranchMissingError(copy.branch)
    if not (copy.root / ".git").is_dir():
        await _ok(copy, "init", "-q")
        await _ok(copy, "remote", "add", _REMOTE, copy.repo.url)
    # L'adresse est reposée à chaque geste : le dépôt d'un workspace peut changer, et le
    # jeton ne s'y écrit jamais (il passe par l'assistant d'identifiants du lanceur).
    await _ok(copy, "remote", "set-url", _REMOTE, copy.repo.url)
    tracking = f"refs/remotes/{_REMOTE}/{copy.branch}"
    # UNE interrogation de la forge au lieu de deux (enabler 782ce1e9). Le `ls-remote`
    # ci-dessus a DÉJÀ rendu le SHA distant : récupérer ensuite des objets qu'on tient
    # déjà est un aller-retour HTTPS pur, avec sa propre poignée de main. Mesuré le
    # 03/11/2026 sur host-test-37 : `ls-remote` 460 ms, `fetch --depth 1` 665 ms, et le
    # travail local de tout l'alignement 15 ms.
    #
    # Ces 15 ms ne valaient que pour un dépôt qui portait alors 9 fichiers suivis : au
    # 15/11/2026, sur une branche de 215 fichiers dont 200 documents YAML, le travail
    # local d'une lecture d'écran pesait au contraire quelques secondes (enabler
    # 1af50397, qui a changé le lecteur YAML). Les deux mesures sont justes à leur date,
    # et c'est leur écart qui enseigne : ne pas conclure d'un profil pris sur un dépôt
    # vide qu'il n'y a rien à gagner côté lecture.
    #
    # CE N'EST PAS UN CACHE, et la distinction est ce qui rend l'économie acceptable :
    # on continue d'INTERROGER la forge à chaque geste, donc une modification faite dans
    # GitHub est toujours vue — « git fait foi » est intact. Il n'y a ni fenêtre de
    # fraîcheur, ni délai, ni état gardé. On n'économise que le transfert d'objets déjà
    # présents, ce que le SHA prouve.
    if remote_head(listed.stdout, ref) != await tracked_sha(copy, tracking):
        await _ok(copy, "fetch", "-q", "--depth", "1", _REMOTE, f"+{ref}:{tracking}")
    # Forcé puis nettoyé : un geste interrompu a pu laisser un commit non poussé, des
    # modifications ou des fichiers non suivis ; aucun ne doit atteindre le geste suivant.
    await _ok(copy, "checkout", "-q", "-f", "-B", copy.branch, tracking)
    await _ok(copy, "clean", "-q", "-fdx")
    copy.head = (await copy.git("rev-parse", "HEAD")).stdout.strip()


async def _ok(copy: WorkCopy, *args: str) -> None:
    result = await copy.git(*args)
    if not result.ok:
        raise RepositoryAccessError(classify(result))
