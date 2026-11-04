from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from miles_socle.events.model import EventAuthor

from miles.git.snapshot import snapshot
from miles.workshop.target import Gesture, WorkBranches

Read = Callable[[str], Awaitable[str | None]]


@dataclass(frozen=True)
class Source:
    """Le paramétrage d'une branche, à sa tête ou à un commit donné, en lecture seule.

    Commun au catalogue et aux lectures ciblées (stories 28f00c74, 1d8396a3) : « lire à
    une version » veut dire la même chose partout.
    """

    commit: str
    paths: Callable[[], Awaitable[list[str]]]
    read: Read


@asynccontextmanager
async def branch_source(
    branches: WorkBranches,
    viewer: EventAuthor,
    workspace_id: str,
    branch: str | None,
    commit: str | None,
) -> AsyncIterator[Source]:
    """La branche à sa tête, ou à `commit` ; un commit inconnu est refusé, jamais remplacé."""
    async with branches.checkout(workspace_id, branch, by=viewer, gesture=Gesture.READ) as copy:
        if commit:
            past = await snapshot(copy, commit)
            yield Source(past.commit, past.paths, past.read)
        else:
            yield Source(copy.head, copy.paths, copy.read)
