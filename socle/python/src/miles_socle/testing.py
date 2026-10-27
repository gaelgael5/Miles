"""Doublures partagées par les suites de tests du socle et des produits.

Livrées DANS le paquet et non dans ses tests : les trois produits ont chacun leur
environnement et leur suite, et aucun ne peut importer les tests d'un autre. Recopier
une doublure d'accès à la base dans chaque suite la ferait diverger de l'interface
réelle d'asyncpg, et c'est précisément ce qu'elle est censée imiter. Pendant du
`@miles/socle-web/testing` côté front.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
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


def write_migrations(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory
