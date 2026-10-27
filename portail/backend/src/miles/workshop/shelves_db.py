from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from miles_socle.events.model import EventAuthor

_SELECT = (
    "SELECT s.workspace_id, w.name AS workspace_name, s.slug, s.holder_directory,"
    " s.holder_subject, s.connection_id, s.shelf_branch, s.shelved_commit, s.shelved_at"
    " FROM branch_shelves s JOIN workspaces w ON w.id = s.workspace_id"
)


@dataclass(frozen=True)
class Shelf:
    """Travail non publié rangé sur la forge au déverrouillage (story fd1eb7da)."""

    workspace_id: str
    workspace_name: str
    slug: str
    holder: EventAuthor
    connection_id: str
    shelf_branch: str
    shelved_commit: str
    shelved_at: datetime

    def owned_by(self, person: EventAuthor) -> bool:
        return (self.holder.directory, self.holder.subject) == (person.directory, person.subject)


def _shelf(row: Any) -> Shelf:
    return Shelf(
        row["workspace_id"],
        row["workspace_name"],
        row["slug"],
        EventAuthor(row["holder_directory"], row["holder_subject"]),
        row["connection_id"],
        row["shelf_branch"],
        row["shelved_commit"],
        row["shelved_at"],
    )


async def db_shelf(db: Any, workspace_id: str, slug: str, person: EventAuthor) -> Shelf | None:
    row = await db.fetchrow(
        f"{_SELECT} WHERE s.workspace_id = $1 AND s.slug = $2"
        " AND s.holder_directory = $3 AND s.holder_subject = $4",
        workspace_id,
        slug,
        person.directory,
        person.subject,
    )
    return None if row is None else _shelf(row)


async def db_shelves(db: Any, workspace_id: str) -> list[Shelf]:
    rows = await db.fetch(
        f"{_SELECT} WHERE s.workspace_id = $1 ORDER BY s.shelved_at", workspace_id
    )
    return [_shelf(r) for r in rows]


async def db_shelves_of(db: Any, person: EventAuthor) -> list[Shelf]:
    rows = await db.fetch(
        f"{_SELECT} WHERE s.holder_directory = $1 AND s.holder_subject = $2 ORDER BY s.shelved_at",
        person.directory,
        person.subject,
    )
    return [_shelf(r) for r in rows]


async def db_insert_shelf(db: Any, shelf: Shelf, by: EventAuthor) -> None:
    await db.execute(
        "INSERT INTO branch_shelves (workspace_id, slug, holder_directory, holder_subject,"
        " connection_id, shelf_branch, shelved_commit, shelved_at, shelved_by_directory,"
        " shelved_by_subject) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        shelf.workspace_id,
        shelf.slug,
        shelf.holder.directory,
        shelf.holder.subject,
        shelf.connection_id,
        shelf.shelf_branch,
        shelf.shelved_commit,
        shelf.shelved_at,
        by.directory,
        by.subject,
    )


async def db_delete_shelf(db: Any, shelf: Shelf) -> None:
    await db.execute(
        "DELETE FROM branch_shelves WHERE workspace_id = $1 AND slug = $2"
        " AND holder_directory = $3 AND holder_subject = $4",
        shelf.workspace_id,
        shelf.slug,
        shelf.holder.directory,
        shelf.holder.subject,
    )
