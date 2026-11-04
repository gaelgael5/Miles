"""Doublures d'accès aux données, partagées par les suites du socle et des produits.

Recopier une doublure d'asyncpg dans chaque suite la ferait diverger de l'interface
réelle, et c'est précisément ce qu'elle est censée imiter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any


class FakeConnection:
    """Doublure d'asyncpg.Connection : enregistre les requêtes, rejoue des réponses."""

    def __init__(self, *, table_exists: bool = True, rows: list[dict[str, Any]] | None = None):
        self.table_exists = table_exists
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_on: str | None = None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.table_exists

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return self.rows

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if self.fail_on is not None and self.fail_on in query:
            raise RuntimeError("échec simulé")
        return "OK"

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield


class FakeSessionDb:
    """Doublure de la table `sessions` : mêmes requêtes, stockage en dictionnaire.

    Vient du portail, où elle servait seule. Déplacée ici parce que la table des sessions
    est au socle : une doublure qui vit chez un consommateur dérive de ce qu'elle imite au
    premier changement de requête, et les deux autres produits ne la voient pas.
    """

    def __init__(self) -> None:
        self.rows: dict[bytes, dict[str, Any]] = {}

    async def execute(self, query: str, *args: Any) -> str:
        if query.startswith("INSERT INTO sessions"):
            digest, kind, subject, expires_at, directory, display_name, email, root_admin = args
            self.rows[digest] = {
                "token_digest": digest,
                "subject_kind": kind,
                "subject": subject,
                "expires_at": expires_at,
                "directory": directory,
                "display_name": display_name,
                "email": email,
                "root_admin": root_admin,
            }
            return "INSERT 0 1"
        if query.startswith("DELETE FROM sessions"):
            self.rows.pop(args[0], None)
            return "DELETE 1"
        raise AssertionError(f"requête inattendue : {query}")

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        digest, now = args
        row = self.rows.get(digest)
        if row is None or not row["expires_at"] > now:
            return None
        return row


class FakeClock:
    """Horloge injectable : un test qui dépend de l'heure réelle échoue un jour sur cent."""

    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current
