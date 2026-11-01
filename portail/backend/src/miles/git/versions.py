"""Enregistrer une version : poser l'étiquette `version/<n>`, et la relire.

La LECTURE est partie au socle le 01/11/2026 (`miles_socle.git.versions`), deuxième
usage : le module d'enrôlement affiche les versions d'un workspace hébergé. C'est la
convention du nom d'étiquette qui devait cesser d'être écrite deux fois.

Ce qui reste ici est ce que le portail SEUL fait — poser l'étiquette, comparer deux
arbres, remettre un arbre dans la copie — plus l'adaptation de la lecture à sa copie de
travail et à son vocabulaire d'erreur.
"""

from __future__ import annotations

from miles_socle.git.failures import GitAccessError, classify
from miles_socle.git.versions import (
    BRANCH_TRAILER,
    TAG_PREFIX,
    SavedVersion,
)
from miles_socle.git.versions import fetch_versions as read_versions

from miles.git.workcopy import WorkCopy, author_parts
from miles.git.worktree import RepositoryAccessError


class VersionTakenError(Exception):
    """Une autre version a pris ce numéro pendant l'enregistrement : rien n'est posé."""


async def fetch_versions(copy: WorkCopy) -> list[SavedVersion]:
    """Versions du dépôt de cette copie, de la plus récente à la plus ancienne.

    Superficiellement (un commit par étiquette) : l'historique complet n'est pas utile
    pour lire un libellé ou comparer deux arbres, et c'est le défaut du socle.

    Le refus du socle est TRADUIT dans l'erreur du produit, et ce n'est pas une politesse :
    tout le portail attrape `RepositoryAccessError` — c'est elle qui devient un 422 avec
    la cause nommée. Laisser remonter `GitAccessError` ferait un 500 sur une forge
    injoignable, et l'écran dirait « erreur interne » là où il doit dire « identifiants ».
    """
    try:
        return await read_versions(copy.git, copy.repo.url)
    except GitAccessError as inaccessible:
        raise RepositoryAccessError(inaccessible.reason) from inaccessible


async def same_tree(copy: WorkCopy, commit: str) -> bool:
    here = await copy.git("rev-parse", "HEAD^{tree}")
    there = await copy.git("rev-parse", f"{commit}^{{tree}}")
    return here.ok and there.ok and here.stdout.strip() == there.stdout.strip()


async def tag_head(copy: WorkCopy, number: int, label: str, author: str) -> None:
    """Pose et pousse `version/<n>` sur la tête lue au départ, au nom de l'auteur.

    Le message porte le libellé, puis la branche de la copie en ligne de pied.
    """
    tagger, email = author_parts(author)
    name = f"{TAG_PREFIX}{number}"
    # Les -c passés ici viennent après ceux du lanceur : l'étiqueteur est la personne,
    # pas le compte technique de Miles.
    tagged = await copy.git(
        "-c",
        f"user.name={tagger}",
        "-c",
        f"user.email={email}",
        "tag",
        "-a",
        name,
        copy.head,
        "-m",
        label,
        "-m",
        f"{BRANCH_TRAILER}: {copy.branch}",
    )
    if not tagged.ok:
        raise RepositoryAccessError(classify(tagged))
    # Sans --force : une étiquette déjà poussée par un enregistrement concurrent fait
    # échouer celui-ci, jamais l'inverse.
    pushed = await copy.git("push", "-q", copy.repo.url, f"refs/tags/{name}")
    if not pushed.ok:
        if "already exists" in pushed.stderr or "rejected" in pushed.stderr:
            raise VersionTakenError(name)
        raise RepositoryAccessError(classify(pushed))


async def restore_tree(copy: WorkCopy, commit: str) -> None:
    """Remet l'arbre de `commit` dans la copie, sans réécrire l'historique."""
    removed = await copy.git("rm", "-rqf", "--ignore-unmatch", ".")
    restored = await copy.git("checkout", commit, "--", ".")
    if not (removed.ok and restored.ok):
        raise RepositoryAccessError(classify(restored))
