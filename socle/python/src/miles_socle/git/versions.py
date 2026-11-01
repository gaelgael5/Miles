"""Lire les versions enregistrées dans un dépôt : les étiquettes annotées `version/<n>`.

Au socle depuis le 01/11/2026, deuxième usage : le module d'enrôlement affiche les
versions d'un workspace hébergé pour en faire choisir une (story 3bbd4f87), après le
portail qui les pose. Ce qui voyage ici n'est pas du code de confort, c'est la
**convention** — le nom de l'étiquette, le champ qui porte le libellé, la ligne de pied
qui nomme la branche. Deux lectures écrites séparément auraient divergé au premier
changement fait d'un seul côté, et le module d'enrôlement aurait affiché « aucune
version » sur un dépôt qui en porte, sans que rien ne le signale.

La POSE d'une étiquette reste au portail (`miles.git.versions`) : il est seul à
enregistrer une version, et le socle n'a aucune raison de savoir en écrire une.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from miles_socle.git.failures import GitAccessError, classify
from miles_socle.git.runner import GitResult

# Une version est une étiquette annotée posée sur un commit de la branche de travail :
# c'est l'un des cinq droits éprouvés (« poser un tag de version »), elle porte libellé,
# auteur et date, et le retour arrière ou la revue avant homologation visent ce commit.
TAG_PREFIX = "version/"
_TAG_RE = re.compile(r"^version/(\d+)$")
_FIELD = "\x1f"
# La branche d'où vient une version, en ligne de pied du message de l'étiquette : le nom
# `version/<n>` reste unique au dépôt (Gael, 22/10/2026), la branche ne s'y lit donc pas.
BRANCH_TRAILER = "Branche"

# Ce qui lance git dans le dépôt où l'on veut lire. Une fonction, et non un objet : les
# deux appelants n'ont pas le même dépôt — une copie de travail jetable d'un côté, un
# miroir persistant de l'autre — et seule la MANIÈRE de lancer git leur est commune.
# Exiger un type commun les aurait forcés à partager aussi leur notion de copie, qui est
# précisément ce qui diffère.
GitCommand = Callable[..., Awaitable[GitResult]]


@dataclass(frozen=True)
class SavedVersion:
    number: int
    label: str
    commit: str
    author: str
    saved_at: datetime
    # None : étiquette posée avant les branches filles (22/10/2026), sans ligne de pied.
    branch: str | None = None


async def fetch_versions(
    git: GitCommand, repo_url: str, *, depth: int | None = 1
) -> list[SavedVersion]:
    """Versions du dépôt, de la plus récente à la plus ancienne.

    `depth` borne ce qui est récupéré, et ce n'est pas qu'une économie :

    - **1** suffit pour LIRE une version — un libellé, un auteur, une date, un arbre à
      comparer — et c'est ce que fait le portail.
    - **None** récupère l'historique complet, et c'est ce qu'exige `git bundle`. Mesuré le
      01/11/2026 dans l'image de production : un bundle fabriqué depuis un dépôt
      superficiel **se crée sans erreur**, puis échoue à l'ouverture sur « did not send
      all necessary objects » — un vert trompeur, et `git bundle create --depth` n'existe
      pas. Le module d'enrôlement, qui doit servir ce bundle à un environnement, récupère
      donc complètement.

    Le choix se fait à la PREMIÈRE récupération et pas après : un dépôt récupéré
    superficiellement reste marqué tel quel, et l'approfondir ensuite est un autre geste
    (`--unshallow`) que celui-ci ne fait pas.
    """
    remote = await git("ls-remote", "--refs", repo_url, f"refs/tags/{TAG_PREFIX}*")
    if not remote.ok:
        raise GitAccessError(classify(remote))
    # git refuse un fetch dont le motif ne trouve rien : sans version, rien à récupérer.
    if not remote.stdout.strip():
        return []
    profondeur = () if depth is None else ("--depth", str(depth))
    fetched = await git(
        "fetch",
        "-q",
        # La copie peut être persistante : une étiquette supprimée sur la forge doit
        # disparaître ici aussi, sinon elle serait encore listée comme version.
        "--prune",
        *profondeur,
        repo_url,
        f"+refs/tags/{TAG_PREFIX}*:refs/tags/{TAG_PREFIX}*",
    )
    if not fetched.ok:
        raise GitAccessError(classify(fetched))
    listed = await git(
        "for-each-ref",
        f"--format=%(refname:short){_FIELD}%(*objectname){_FIELD}%(taggername) %(taggeremail)"
        f"{_FIELD}%(taggerdate:iso-strict){_FIELD}%(contents:subject)"
        f"{_FIELD}%(trailers:key={BRANCH_TRAILER},valueonly,separator=)",
        f"refs/tags/{TAG_PREFIX}",
    )
    versions = [v for v in map(parse_version_line, listed.stdout.splitlines()) if v is not None]
    return sorted(versions, key=lambda v: v.number, reverse=True)


def parse_version_line(line: str) -> SavedVersion | None:
    """Une ligne du format ci-dessus, ou None si ce n'est pas une version de Miles."""
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
