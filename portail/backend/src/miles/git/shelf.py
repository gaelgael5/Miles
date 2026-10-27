from __future__ import annotations

from miles.git.holdspace import HeldCopy
from miles.git.rights import Reason, classify
from miles.git.workcopy import author_parts
from miles.git.worktree import RepositoryAccessError

# Rangement d'un travail non publié (story fd1eb7da) : une branche de la forge, poussée et
# relue avec le jeton de la personne, jamais celui du service.
_REMOTE = "origin"


class ShelfTakenError(Exception):
    """Un rangement porte déjà ce nom sur la forge : on ne l'écrase jamais."""


class ShelfMissingError(Exception):
    """Le rangement n'est plus sur la forge (supprimé dans GitHub)."""


async def shelve(copy: HeldCopy, name: str) -> str:
    """Pousse la tête de l'espace sur `name`, puis vérifie qu'elle y est ; rend le commit.

    Bail vide : la branche ne doit pas exister. Un rangement déjà là n'est pas écrasé.
    """
    ref = f"refs/heads/{name}"
    pushed = await copy.git(
        "push", "-q", f"--force-with-lease={ref}:", copy.repo.url, f"HEAD:{ref}"
    )
    if not pushed.ok:
        if "stale info" in pushed.stderr or "rejected" in pushed.stderr:
            raise ShelfTakenError(name)
        raise RepositoryAccessError(classify(pushed))
    # Relu sur la forge avant que quoi que ce soit ne soit supprimé : l'espace porte la
    # seule autre copie de ce travail.
    if await _remote_tip(copy, name) != copy.head:
        raise RepositoryAccessError(Reason.FAILED)
    return copy.head


async def merge_shelf(copy: HeldCopy, name: str) -> tuple[str, list[str]]:
    """Fusionne le rangement dans l'espace ; rend (tête rangée, fichiers en conflit).

    En conflit, la fusion est abandonnée : l'espace revient à son état d'avant, rien
    n'est écrit (critère 7).
    """
    tip = await _remote_tip(copy, name)
    if tip is None:
        raise ShelfMissingError(name)
    shallow = await copy.git("rev-parse", "--is-shallow-repository")
    # Une fusion a besoin de l'ancêtre commun, que le clone superficiel n'a pas.
    deepen = ["--unshallow"] if shallow.stdout.strip() == "true" else []
    fetched = await copy.git(
        "fetch",
        "-q",
        *deepen,
        _REMOTE,
        f"+refs/heads/{copy.branch}:refs/remotes/{_REMOTE}/{copy.branch}",
        f"+refs/heads/{name}:refs/remotes/{_REMOTE}/{name}",
    )
    if not fetched.ok:
        raise RepositoryAccessError(classify(fetched))
    person, email = author_parts(copy.signature)
    merged = await copy.git(
        "-c",
        f"user.name={person}",
        "-c",
        f"user.email={email}",
        "merge",
        "-q",
        "--no-edit",
        f"refs/remotes/{_REMOTE}/{name}",
    )
    if merged.ok:
        copy.head = (await copy.git("rev-parse", "HEAD")).stdout.strip()
        return tip, []
    conflicted = await copy.git("diff", "--name-only", "--diff-filter=U")
    await copy.git("merge", "--abort")
    files = sorted(p for p in conflicted.stdout.splitlines() if p)
    if not files:
        raise RepositoryAccessError(classify(merged))
    return tip, files


async def drop_shelf(copy: HeldCopy, name: str, tip: str) -> None:
    """Supprime le rangement fusionné, s'il est toujours à la tête fusionnée."""
    ref = f"refs/heads/{name}"
    dropped = await copy.git(
        "push", "-q", f"--force-with-lease={ref}:{tip}", copy.repo.url, f":{ref}"
    )
    if not dropped.ok:
        raise RepositoryAccessError(classify(dropped))


async def _remote_tip(copy: HeldCopy, name: str) -> str | None:
    listed = await copy.git("ls-remote", "--heads", copy.repo.url, f"refs/heads/{name}")
    if not listed.ok:
        raise RepositoryAccessError(classify(listed))
    line = listed.stdout.strip()
    return line.split()[0] if line else None
