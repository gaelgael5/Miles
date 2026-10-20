from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

BASE_ENV = "MILES_DB_PASSWORD=d0nt-t0uch-me\nMILES_HTTP_PORT=8180\n"
ADMIN_PASSWORD = "correct horse battery"


def write_env(tmp_path: Path, content: str = BASE_ENV) -> tuple[Path, Path]:
    """.env et .env.bak tels que dev-deploy.sh les prépare : les deux existent."""
    env, backup = tmp_path / ".env", tmp_path / ".env.bak"
    env.write_text(content, encoding="utf-8")
    env.chmod(0o600)
    backup.write_text("", encoding="utf-8")
    backup.chmod(0o600)
    return env, backup


class FakeSessionDb:
    """Doublure de la table sessions : mêmes requêtes, stockage en dictionnaire."""

    def __init__(self) -> None:
        self.rows: dict[bytes, dict[str, Any]] = {}

    async def execute(self, query: str, *args: Any) -> str:
        if query.startswith("INSERT INTO sessions"):
            digest, kind, subject, expires_at, directory, display_name, email = args
            self.rows[digest] = {
                "token_digest": digest,
                "subject_kind": kind,
                "subject": subject,
                "expires_at": expires_at,
                "directory": directory,
                "display_name": display_name,
                "email": email,
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
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current
