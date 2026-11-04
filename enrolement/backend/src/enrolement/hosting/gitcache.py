"""Le miroir git des workspaces hébergés : où ce module lit les versions, et les sert.

Un CACHE, et rien de plus : git fait foi, chaque geste repart de la forge, et supprimer ce
répertoire ne perd rien — il se refait à la lecture suivante. C'est ce qui permet de ne pas
exiger son volume au démarrage.

Deux décisions de sécurité vivent ici, au point où elles s'appliquent, et pas ailleurs.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from miles_socle.git.access import GitAccess
from miles_socle.git.failures import GitAccessError, classify
from miles_socle.git.forge import Repository
from miles_socle.git.runner import GitResult, run_git
from miles_socle.git.versions import TAG_PREFIX
from miles_socle.signing.hosting import MAX_BUNDLE_BYTES

log = structlog.get_logger(__name__)

GitCommand = Callable[..., Awaitable[GitResult]]
# Assez pour distinguer sans ambiguïté pratique, assez court pour qu'un chemin reste
# lisible quand on diagnostique sur la machine.
_DIGEST_LENGTH = 32
# Le nom du workspace, déposé en clair DANS son répertoire. Le répertoire est nommé par une
# empreinte (voir ci-dessous) : sans ce fichier, personne ne saurait à quoi correspond un
# dossier en regardant le volume.
_LABEL_FILE = ".workspace"


@dataclass
class HostingCache:
    """Un miroir persistant par workspace hébergé, sur le volume monté.

    **Le répertoire est nommé par une EMPREINTE de l'identifiant, jamais par l'identifiant.**
    Cet identifiant vient du module de paramétrage par le réseau, et sa seule contrainte
    est celle de `confided_git_workspace.id` : une à deux cents caractères imprimables.
    Autrement dit il peut contenir « / », « .. », des espaces — tout ce qu'il faut pour
    sortir du volume. Le valider plus strictement aurait été l'autre voie, et elle a été
    écartée : elle ferait refuser ici un identifiant que le pair nous a pourtant transmis
    et que son écran affiche, sur un message que personne ne saurait relier à sa cause.
    L'empreinte, elle, est sûre quoi que le pair envoie.

    **Le miroir est COMPLET, jamais superficiel.** Mesuré le 01/11/2026 dans l'image de
    production : un bundle fabriqué depuis un dépôt récupéré en `--depth 1` se crée sans
    erreur puis échoue à l'ouverture sur « did not send all necessary objects », et
    `git bundle create --depth` n'existe pas. Comme ce miroir sert à la fois à lire les
    versions et à les SERVIR, il récupère tout. Un dépôt récupéré superficiellement une
    seule fois resterait marqué tel quel, d'où le choix dès la première récupération.
    """

    root: Path
    # Un geste à la fois par répertoire : deux requêtes sur le même miroir se
    # piétineraient les références. Le back-office tourne en un seul processus.
    _locks: dict[Path, asyncio.Lock] = field(default_factory=dict)

    def directory(self, workspace_id: str) -> Path:
        empreinte = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
        # Le contrôle reste, bien que l'empreinte soit hexadécimale par construction : il
        # coûte une comparaison, et c'est la ligne qui garantit qu'aucune évolution du
        # nommage ne fera écrire hors du volume.
        target = (self.root / empreinte).resolve()
        if not target.is_relative_to(self.root.resolve()):  # pragma: no cover - garde de fond
            raise ValueError("miroir hors du volume")
        return target

    @asynccontextmanager
    async def opened(self, workspace_id: str, access: GitAccess) -> AsyncIterator[GitCommand]:
        """Le miroir de ce workspace, prêt à recevoir des commandes git, un geste à la fois."""
        directory = self.directory(workspace_id)
        lock = self._locks.setdefault(directory, asyncio.Lock())
        async with lock:
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(
                (directory / _LABEL_FILE).write_text, workspace_id + "\n", "utf-8"
            )

            def git(*args: str) -> Awaitable[GitResult]:
                return run_git(list(args), directory, access)

            if not (directory / ".git").is_dir():
                lancé = await git("init", "-q")
                if not lancé.ok:
                    raise GitAccessError(classify(lancé))
            yield git

    async def forget(self, workspace_id: str) -> None:
        """Retire le miroir d'un workspace. Ce n'est qu'un cache : rien n'est perdu."""
        await asyncio.to_thread(shutil.rmtree, self.directory(workspace_id), True)


async def file_bundle(git: GitCommand, repo: Repository, number: int) -> bytes:
    """Le contenu de `version/<n>` sous forme de bundle git, lu en mémoire.

    **Par un fichier temporaire et non par la sortie standard** : le lanceur du socle
    décode ce que git écrit en UTF-8 avec remplacement — ce qu'il faut pour un message
    d'erreur, ce qui détruirait un bundle. Le fichier vit le temps de l'appel et part avec
    son répertoire, quoi qu'il arrive.

    La taille est vérifiée AVANT la lecture : une charge démesurée n'a pas à être montée
    en mémoire pour qu'on découvre ensuite qu'elle dépasse ce que le contrat accepte.
    """
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-bundle-"))
    try:
        paquet = workdir / "version.bundle"
        fait = await git("bundle", "create", str(paquet), f"{TAG_PREFIX}{number}")
        if not fait.ok:
            log.warning("bundle_refuse_par_git", repo=repo.name, number=number)
            raise GitAccessError(classify(fait))
        taille = (await asyncio.to_thread(paquet.stat)).st_size
        if taille > MAX_BUNDLE_BYTES:
            log.warning("bundle_trop_volumineux", repo=repo.name, number=number, bytes=taille)
            raise BundleTooLargeError(taille)
        return await asyncio.to_thread(paquet.read_bytes)
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


class BundleTooLargeError(Exception):
    """Le bundle dépasse ce que le contrat accepte de faire voyager.

    Refusé ICI plutôt que chez le destinataire : lui le refuserait aussi, mais après
    l'avoir reçu — et nous l'aurions lu en mémoire pour rien.
    """

    def __init__(self, size: int) -> None:
        super().__init__(f"bundle de {size} octets, au-delà de {MAX_BUNDLE_BYTES}")
        self.size = size
