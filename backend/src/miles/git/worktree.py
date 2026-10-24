from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miles.git.access import GitAccess
from miles.git.forge import Repository
from miles.git.rights import Reason, classify
from miles.git.runner import GitResult, run_git

# Les branches de Miles vivent sous « back/<workspace>/ » (Gael, 24/10/2026) : « back/ »
# les sépare des branches humaines du dépôt, et le workspace les isole les unes des autres.
# Un préfixe « work/ » commun suffisait tant qu'un dépôt ne servait qu'un workspace ; il ne
# disait pas à qui une branche appartenait, ce que l'écran doit pouvoir lire du seul nom.
WORK_BRANCH_ROOT = "back/"
WORK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# Identifiant de workspace, tel que la base le contraint (migration 0009). Revalidé ici :
# il entre dans une référence git, et une référence ne se construit pas par concaténation
# d'une valeur non vérifiée.
WORKSPACE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
MANIFEST = "manifest.json"
# Contenu initial du manifeste. Le plancher de version reste un point ouvert du cadrage
# (« déclaration du plancher de version ») : null dit « aucun », sans en inventer un.
INITIAL_MANIFEST: dict[str, Any] = {
    "format_version": 1,
    "min_app_version": None,
    "capabilities": [],
}

# Arborescence retenue au cadrage (« Back-office — capacités attendues »). Elle porte
# le métier par domaine et le transverse à la racine — et aucun dossier d'environnement.
_SHARED = {"messages", "components", "referentials", "theme"}
_DOMAIN = {"messages", "mappings", "referentials", "components", "screens", "scenarios"}
_MAPPINGS = {"inbound", "outbound"}
SKELETON = (
    "contracts",
    *(f"shared/{d}" for d in sorted(_SHARED)),
    "domains",
    # Chaînes de transformations (Gael, 22/10/2026) : un répertoire par chaîne, à la
    # racine puisque le dépôt est déjà propre à une application.
    "transformations",
    # Sources de données (story 66391afe), à la racine pour la même raison.
    "sources",
)
# Fichiers que poussent les forges ou les outils à la création d'un dépôt : un dépôt qui
# n'a qu'eux est vierge, pas « non conforme ».
_TOLERATED_ROOT = {"README", "README.md", "LICENSE", "LICENSE.md", ".gitignore", ".gitattributes"}
# Noms qui trahissent un dossier par environnement : l'environnement est une branche.
_ENVIRONMENT_NAMES = re.compile(
    r"^(env|envs|environments?|environnements?|prod.*|preprod.*|recette.*|staging|dev|test|qa)$",
    re.I,
)


class WorkBranchError(Exception):
    """Refus ; rien n'a été écrit dans le dépôt."""


class RepositoryAccessError(WorkBranchError):
    def __init__(self, reason: Reason) -> None:
        super().__init__(f"dépôt inaccessible : {reason.value}")
        self.reason = reason


class BranchExistsError(WorkBranchError):
    pass


@dataclass
class TreeDiagnosis:
    unexpected: list[str] = field(default_factory=list)
    environment_dirs: list[str] = field(default_factory=list)
    manifest: str = "absent"  # absent | invalide | valide

    @property
    def conform(self) -> bool:
        return not self.unexpected and not self.environment_dirs and self.manifest == "valide"


class NonConformTreeError(WorkBranchError):
    """Arborescence non conforme : on ne modifie rien et on dit pourquoi (critère 5)."""

    def __init__(self, diagnosis: TreeDiagnosis) -> None:
        super().__init__("arborescence non conforme")
        self.diagnosis = diagnosis


@dataclass(frozen=True)
class WorkBranch:
    branch: str
    # Branche créée par Miles : « initialisee » (un commit a posé l'ossature) ou
    # « conforme » (rien n'a été écrit). Branche qui préexistait et qu'on a reprise :
    # « reprise » (rien n'a été écrit) ou « reprise_initialisee » (elle était vide et a
    # reçu l'ossature). Les quatre valeurs sont contraintes en base (migration 0023).
    outcome: str


def _has_ref(ls_remote: str, ref: str) -> bool:
    """Référence présente, comparée EXACTEMENT ligne à ligne (« <sha>\t<ref> »).

    Chercher la sous-chaîne confond « back/ams/atelier » avec « back/ams/atelier-bis » : la
    branche demandée devient alors inouvrable, refusée à l'ouverture puis introuvable
    au clone de la reprise (relevé en revue, 23/10/2026).
    """
    return any(line.split("\t")[-1].strip() == ref for line in ls_remote.splitlines())


def work_branch_prefix(workspace_id: str) -> str:
    """Espace de noms des branches de ce workspace : « back/<workspace>/ »."""
    if not WORKSPACE_ID_RE.match(workspace_id):
        raise ValueError("identifiant de workspace invalide")
    return f"{WORK_BRANCH_ROOT}{workspace_id}/"


def work_branch_name(workspace_id: str, name: str) -> str:
    if not WORK_NAME_RE.match(name):
        raise ValueError("nom de branche de travail invalide")
    return work_branch_prefix(workspace_id) + name


def diagnose(paths: list[str], manifest_text: str | None) -> TreeDiagnosis:
    """Compare les chemins du dépôt à l'arborescence retenue, sans rien écrire."""
    diagnosis = TreeDiagnosis(manifest=_manifest_state(manifest_text))
    for path in paths:
        parts = path.split("/")
        if _is_environment(parts):
            top = parts[0]
            if top not in diagnosis.environment_dirs:
                diagnosis.environment_dirs.append(top)
        elif not _allowed(parts):
            diagnosis.unexpected.append(path)
    return diagnosis


def is_blank(paths: list[str]) -> bool:
    return all(path in _TOLERATED_ROOT or path.startswith(".github/") for path in paths)


def _manifest_state(text: str | None) -> str:
    if text is None:
        return "absent"
    try:
        data = json.loads(text)
    except ValueError:
        return "invalide"
    valid = (
        isinstance(data, dict)
        and data.get("format_version") == 1
        and isinstance(data.get("capabilities"), list)
        and all(isinstance(c, str) for c in data["capabilities"])
        and (data.get("min_app_version") is None or isinstance(data["min_app_version"], str))
    )
    return "valide" if valid else "invalide"


def _is_environment(parts: list[str]) -> bool:
    return len(parts) > 1 and bool(_ENVIRONMENT_NAMES.match(parts[0]))


def _allowed(parts: list[str]) -> bool:
    top = parts[0]
    if len(parts) == 1:
        return top == MANIFEST or top in _TOLERATED_ROOT
    if top == ".github":
        return True
    if top in ("contracts", "transformations", "sources"):
        # Le contenu d'une chaîne se vérifie avec la chaîne (validation de la branche).
        return True
    if top == "shared":
        return parts[1] in _SHARED or parts[1] == ".gitkeep"
    if top == "domains":
        return _allowed_in_domain(parts[2:]) if len(parts) > 2 else True
    return False


def _allowed_in_domain(rest: list[str]) -> bool:
    if len(rest) <= 1:
        return not rest or rest[0] == ".gitkeep"
    if rest[0] not in _DOMAIN:
        return False
    if rest[0] == "mappings" and len(rest) > 2:
        return rest[1] in _MAPPINGS
    return True


async def open_work_branch(
    repo: Repository,
    access: GitAccess,
    workspace_id: str,
    name: str,
    author: str,
    *,
    adopt_existing: bool = False,
) -> WorkBranch:
    """Ouvre la branche de travail ; `adopt_existing` reprend celle qui est déjà au dépôt.

    Le rattachement est un second geste, jamais le premier : sans lui, une branche
    homonyme est refusée (BranchExistsError) et rien n'est touché. C'est l'écran qui
    demande confirmation, puis rejoue avec adopt_existing (Gael, 23/10/2026).
    """
    branch = work_branch_name(workspace_id, name)
    workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-work-"))
    try:
        return await _Opener(repo, access, workdir, branch, author, adopt_existing).run()
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)


@dataclass
class _Opener:
    repo: Repository
    access: GitAccess
    workdir: Path
    branch: str
    author: str
    adopt_existing: bool = False

    async def git(self, *args: str, cwd: Path | None = None) -> GitResult:
        return await run_git(list(args), cwd or self.workdir, self.access)

    async def run(self) -> WorkBranch:
        heads = await self.git("ls-remote", "--symref", self.repo.url, "HEAD", "refs/heads/*")
        if not heads.ok:
            raise RepositoryAccessError(classify(heads))
        existing = _has_ref(heads.stdout, f"refs/heads/{self.branch}")
        if existing and not self.adopt_existing:
            raise BranchExistsError(self.branch)
        # Reprise demandée mais la branche a disparu entre la confirmation et ici : on la
        # crée, ce qui est exactement ce que la personne demandait. Un refus l'obligerait
        # à refaire le même geste pour le même résultat.
        default = _default_branch(heads.stdout)
        clone = self.workdir / "clone"
        # On part de la branche elle-même quand on la reprend : son contenu fait foi, pas
        # celui de la branche par défaut, qui l'écraserait à la poussée.
        source = self.branch if existing else default
        if source is None:
            await self.git("init", "-q", "-b", self.branch, str(clone))
            paths: list[str] = []
        else:
            cloned = await self.git(
                "clone", "-q", "--depth", "1", "--branch", source, self.repo.url, str(clone)
            )
            if not cloned.ok:
                raise RepositoryAccessError(classify(cloned))
            listed = await self.git("ls-tree", "-r", "--name-only", "HEAD", cwd=clone)
            paths = [line for line in listed.stdout.splitlines() if line]
            if not existing:
                await self.git("checkout", "-q", "-b", self.branch, cwd=clone)
        outcome = await self._prepare(clone, paths)
        if existing:
            # Une branche qu'on reprend ne s'enregistre jamais comme une création : le
            # journal doit pouvoir dire, après coup, que Miles s'est branché sur
            # l'existant. « reprise » seule ne distinguerait pas la branche vide qu'on a
            # dû initialiser — et c'est le seul cas où la reprise écrit quelque chose.
            outcome = "reprise" if outcome == "conforme" else "reprise_initialisee"
        pushed = await self.git(
            "push", "-q", self.repo.url, f"HEAD:refs/heads/{self.branch}", cwd=clone
        )
        if not pushed.ok:
            raise RepositoryAccessError(classify(pushed))
        return WorkBranch(self.branch, outcome)

    async def _prepare(self, clone: Path, paths: list[str]) -> str:
        if is_blank(paths):
            await asyncio.to_thread(_write_skeleton, clone)
            await self.git("add", "-A", cwd=clone)
            committed = await self.git(
                "commit",
                "-q",
                f"--author={self.author}",
                "-m",
                "Initialisation de l'arborescence de paramétrage",
                cwd=clone,
            )
            if not committed.ok:
                raise RepositoryAccessError(Reason.FAILED)
            return "initialisee"
        manifest = await asyncio.to_thread(_read_text, clone / MANIFEST)
        diagnosis = diagnose(paths, manifest)
        if not diagnosis.conform:
            # Jamais d'écriture optimiste sur une arborescence qu'on ne reconnaît pas.
            raise NonConformTreeError(diagnosis)
        return "conforme"


def _default_branch(ls_remote: str) -> str | None:
    """Branche par défaut annoncée par la forge ; à défaut main, puis la première listée.

    Jamais « aucune » quand des branches existent : ce serait traiter comme vierge un
    dépôt qui a du contenu, et y écrire une ossature sans l'avoir diagnostiqué.
    """
    heads: list[str] = []
    for line in ls_remote.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line.removeprefix("ref: refs/heads/").split("\t", 1)[0]
        ref = line.split("\t", 1)[-1]
        if ref.startswith("refs/heads/"):
            heads.append(ref.removeprefix("refs/heads/"))
    if "main" in heads:
        return "main"
    return sorted(heads)[0] if heads else None


def _write_skeleton(root: Path) -> None:
    for directory in SKELETON:
        target = root / directory
        target.mkdir(parents=True, exist_ok=True)
        # git ne versionne pas un dossier vide : un marqueur garde l'ossature visible.
        (target / ".gitkeep").write_text("", encoding="utf-8")
    (root / MANIFEST).write_text(json.dumps(INITIAL_MANIFEST, indent=2) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def diagnosis_json(diagnosis: TreeDiagnosis) -> dict[str, Any]:
    return {
        "unexpected": diagnosis.unexpected,
        "environment_dirs": diagnosis.environment_dirs,
        "manifest": diagnosis.manifest,
    }
