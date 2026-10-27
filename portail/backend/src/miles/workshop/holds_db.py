from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from miles.events.model import EventAuthor

_SELECT = (
    "SELECT h.workspace_id, h.slug, h.holder_directory, h.holder_subject, h.connection_id,"
    " h.published_commit, h.taken_at, i.name, i.login FROM branch_holds h"
    " LEFT JOIN user_git_identities i ON i.viewer_directory = h.holder_directory"
    " AND i.viewer_subject = h.holder_subject AND i.connection_id = h.connection_id"
)


@dataclass(frozen=True)
class Hold:
    workspace_id: str
    slug: str
    holder: EventAuthor
    connection_id: str
    published_commit: str
    taken_at: datetime
    # Ce qu'on affiche de qui la tient : son nom et son login de forge.
    holder_label: str
    # Son login de forge : il nomme son rangement (fd1eb7da). None sans identité git.
    holder_login: str | None = None

    def held_by(self, person: EventAuthor) -> bool:
        # (annuaire, sub) seulement : un auteur passé par MCP est la même personne.
        return (self.holder.directory, self.holder.subject) == (person.directory, person.subject)


def _hold(row: Any) -> Hold:
    login, name = row["login"], row["name"]
    label = f"{name} ({login})" if login else row["holder_subject"]
    return Hold(
        row["workspace_id"],
        row["slug"],
        EventAuthor(row["holder_directory"], row["holder_subject"]),
        row["connection_id"],
        row["published_commit"],
        row["taken_at"],
        label,
        login,
    )


async def db_hold(db: Any, workspace_id: str, slug: str) -> Hold | None:
    row = await db.fetchrow(
        f"{_SELECT} WHERE h.workspace_id = $1 AND h.slug = $2", workspace_id, slug
    )
    return None if row is None else _hold(row)


async def db_hold_of(db: Any, person: EventAuthor) -> Hold | None:
    row = await db.fetchrow(
        f"{_SELECT} WHERE h.holder_directory = $1 AND h.holder_subject = $2",
        person.directory,
        person.subject,
    )
    return None if row is None else _hold(row)


async def db_holds(db: Any, workspace_id: str) -> list[Hold]:
    rows = await db.fetch(f"{_SELECT} WHERE h.workspace_id = $1", workspace_id)
    return [_hold(r) for r in rows]


async def db_holds_on_connection(db: Any, person: EventAuthor, connection_id: str) -> list[Hold]:
    rows = await db.fetch(
        f"{_SELECT} WHERE h.holder_directory = $1 AND h.holder_subject = $2"
        " AND h.connection_id = $3",
        person.directory,
        person.subject,
        connection_id,
    )
    return [_hold(r) for r in rows]


async def db_set_published(db: Any, hold: Hold, commit: str) -> None:
    await db.execute(
        "UPDATE branch_holds SET published_commit = $3 WHERE workspace_id = $1 AND slug = $2",
        hold.workspace_id,
        hold.slug,
        commit,
    )
