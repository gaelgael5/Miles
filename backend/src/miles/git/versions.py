from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from miles.git.rights import classify
from miles.git.workcopy import WorkCopy
from miles.git.worktree import RepositoryAccessError

# Une version est une étiquette annotée posée sur un commit de la branche de travail :
# c'est l'un des cinq droits éprouvés (« poser un tag de version »), elle porte libellé,
# auteur et date, et le retour arrière ou la revue avant homologation visent ce commit.
TAG_PREFIX = "version/"
_TAG_RE = re.compile(r"^version/(\d+)$")
_AUTHOR_RE = re.compile(r"^(?P<name>[^<>]+) <(?P<email>[^<>]+)>$")
_FIELD = "\x1f"
# La branche d'où vient une version, en ligne de pied du message de l'étiquette : le nom
# `version/<n>` reste unique au dépôt (Gael, 22/10/2026), la branche ne s'y lit donc pas.
BRANCH_TRAILER = "Branche"


class VersionTakenError(Exception):
    """Une autre version a pris ce numéro pendant l'enregistrement : rien n'est posé."""


@dataclass(frozen=True)
class SavedVersion:
    number: int
    label: str
    commit: str
    author: str
    saved_at: datetime
    # None : étiquette posée avant les branches filles (22/10/2026), sans ligne de pied.
    branch: str | None = None


async def fetch_versions(copy: WorkCopy) -> list[SavedVersion]:
    """Versions du dépôt, de la plus récente à la plus ancienne.

    Récupérées superficiellement (un commit par étiquette) : l'historique complet n'est
    pas utile pour lire un libellé ou comparer deux arbres.
    """
    remote = await copy.git("ls-remote", "--refs", copy.repo.url, f"refs/tags/{TAG_PREFIX}*")
    if not remote.ok:
        raise RepositoryAccessError(classify(remote))
    # git refuse un fetch dont le motif ne trouve rien : sans version, rien à récupérer.
    if not remote.stdout.strip():
        return []
    fetched = await copy.git(
        "fetch",
        "-q",
        "--depth",
        "1",
        copy.repo.url,
        f"+refs/tags/{TAG_PREFIX}*:refs/tags/{TAG_PREFIX}*",
    )
    if not fetched.ok:
        raise RepositoryAccessError(classify(fetched))
    listed = await copy.git(
        "for-each-ref",
        f"--format=%(refname:short){_FIELD}%(*objectname){_FIELD}%(taggername) %(taggeremail)"
        f"{_FIELD}%(taggerdate:iso-strict){_FIELD}%(contents:subject)"
        f"{_FIELD}%(trailers:key={BRANCH_TRAILER},valueonly,separator=)",
        f"refs/tags/{TAG_PREFIX}",
    )
    versions = [v for v in map(_parse, listed.stdout.splitlines()) if v is not None]
    return sorted(versions, key=lambda v: v.number, reverse=True)


def _parse(line: str) -> SavedVersion | None:
    parts = line.split(_FIELD)
    # Une étiquette légère ou hors convention n'est pas une version enregistrée par Miles.
    if len(parts) != 6 or not parts[1]:
        return None
    match = _TAG_RE.match(parts[0])
    if match is None:
        return None
    return SavedVersion(
        int(match[1]),
        parts[4],
        parts[1],
        parts[2],
        datetime.fromisoformat(parts[3]),
        parts[5] or None,
    )


async def same_tree(copy: WorkCopy, commit: str) -> bool:
    here = await copy.git("rev-parse", "HEAD^{tree}")
    there = await copy.git("rev-parse", f"{commit}^{{tree}}")
    return here.ok and there.ok and here.stdout.strip() == there.stdout.strip()


async def tag_head(copy: WorkCopy, number: int, label: str, author: str) -> None:
    """Pose et pousse `version/<n>` sur la tête lue au départ, au nom de l'auteur.

    Le message porte le libellé, puis la branche de la copie en ligne de pied.
    """
    match = _AUTHOR_RE.match(author)
    if match is None:
        raise ValueError("auteur de commit mal formé")
    name = f"{TAG_PREFIX}{number}"
    # Les -c passés ici viennent après ceux du lanceur : l'étiqueteur est la personne,
    # pas le compte technique de Miles.
    tagged = await copy.git(
        "-c",
        f"user.name={match['name']}",
        "-c",
        f"user.email={match['email']}",
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
