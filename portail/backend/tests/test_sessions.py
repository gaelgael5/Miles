from __future__ import annotations

from datetime import UTC, datetime, timedelta

from miles_socle.auth.sessions import (
    db_create_session,
    db_delete_session,
    db_find_session,
    new_session_token,
    token_digest,
)

from tests.auth_fixtures import FakeSessionDb

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_new_session_token_digest_matches_and_tokens_differ() -> None:
    token, digest = new_session_token()
    other, _ = new_session_token()

    assert token_digest(token) == digest
    assert token != other
    assert token.encode() not in digest


async def test_db_find_session_returns_created_session() -> None:
    db = FakeSessionDb()
    await db_create_session(db, b"d", "local_admin", "admin", NOW + timedelta(hours=1))

    session = await db_find_session(db, b"d", NOW)

    assert session is not None
    assert (session.subject_kind, session.subject) == ("local_admin", "admin")


async def test_db_find_session_unknown_digest_returns_none() -> None:
    assert await db_find_session(FakeSessionDb(), b"absent", NOW) is None


async def test_db_find_session_expired_returns_none() -> None:
    db = FakeSessionDb()
    await db_create_session(db, b"d", "local_admin", "admin", NOW)

    assert await db_find_session(db, b"d", NOW) is None


async def test_db_delete_session_removes_it() -> None:
    db = FakeSessionDb()
    await db_create_session(db, b"d", "local_admin", "admin", NOW + timedelta(hours=1))

    await db_delete_session(db, b"d")

    assert await db_find_session(db, b"d", NOW) is None
