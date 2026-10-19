from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from miles.events.journal import db_object_history, db_write_event
from miles.events.model import (
    EventAuthor,
    EventError,
    EventTypeCatalog,
    NewEvent,
    ObjectRef,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CATALOG = EventTypeCatalog(frozenset({"group.created", "device.assigned"}))
AUTHOR = EventAuthor("local", "admin")


class _FakeEventDb:
    def __init__(self, *, in_transaction: bool = True, history: list[dict[str, Any]] | None = None):
        self.in_transaction = in_transaction
        self.history = history or []
        self.counters: dict[tuple[str, str], int] = {}
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def is_in_transaction(self) -> bool:
        return self.in_transaction

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "event_object_sequences" in query:
            rows = []
            for kind, object_id in zip(args[0], args[1], strict=True):
                value = self.counters.get((kind, object_id), 0) + 1
                self.counters[(kind, object_id)] = value
                rows.append({"object_kind": kind, "object_id": object_id, "last_sequence": value})
            return rows
        return self.history


def _event(**overrides: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "type": "group.created",
        "objects": (ObjectRef("group", "g1"),),
        "author": AUTHOR,
    }
    fields.update(overrides)
    return NewEvent(**fields)


async def test_write_event_outside_transaction_is_refused() -> None:
    db = _FakeEventDb(in_transaction=False)

    with pytest.raises(EventError, match="transaction"):
        await db_write_event(db, _event(), CATALOG, lambda: NOW)

    assert db.executed == []


async def test_write_event_unknown_type_is_refused_before_any_write() -> None:
    db = _FakeEventDb()

    with pytest.raises(EventError, match="inconnu du catalogue"):
        await db_write_event(db, _event(type="group.renamed"), CATALOG, lambda: NOW)

    assert db.executed == [] and db.counters == {}


async def test_write_event_empty_catalog_refuses_everything() -> None:
    with pytest.raises(EventError, match="inconnu"):
        await db_write_event(_FakeEventDb(), _event(), EventTypeCatalog(), lambda: NOW)


async def test_write_event_without_functional_date_uses_write_time_and_says_so() -> None:
    written = await db_write_event(_FakeEventDb(), _event(), CATALOG, lambda: NOW)

    assert written.functional_at == NOW
    assert written.functional_at_source == "write_time"


async def test_write_event_keeps_caller_date_past_and_flags_future() -> None:
    past = await db_write_event(
        _FakeEventDb(), _event(functional_at=NOW - timedelta(days=3)), CATALOG, lambda: NOW
    )
    future = await db_write_event(
        _FakeEventDb(), _event(functional_at=NOW + timedelta(hours=1)), CATALOG, lambda: NOW
    )

    assert (past.functional_at, past.functional_at_source) == (NOW - timedelta(days=3), "caller")
    assert not past.functional_at_in_future
    assert future.functional_at_in_future


async def test_write_event_numbers_each_object_and_writes_properties() -> None:
    db = _FakeEventDb()
    db.counters[("device", "d2")] = 6
    event = _event(
        type="device.assigned",
        objects=(ObjectRef("group", "g1"), ObjectRef("device", "d2")),
        properties={"group": "g1"},
    )

    written = await db_write_event(db, event, CATALOG, lambda: NOW)

    assert written.sequences == {ObjectRef("group", "g1"): 1, ObjectRef("device", "d2"): 7}
    insert_event = db.executed[0][1]
    assert json.loads(insert_event[-1]) == {"group": "g1"}
    # Les objets sont envoyés triés : ordre de verrouillage fixe.
    assert db.executed[1][1][0] == ["device", "group"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"objects": ()}, "au moins un objet"),
        ({"objects": (ObjectRef("group", "g1"), ObjectRef("group", "g1"))}, "deux fois"),
        ({"type": "Group Created"}, "type d'event invalide"),
        ({"functional_at": datetime(2026, 10, 19)}, "sans fuseau"),
    ],
)
def test_new_event_rejects_malformed_events(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(EventError, match=message):
        _event(**overrides)


@pytest.mark.parametrize(("directory", "subject"), [("", "admin"), ("local", "")])
def test_event_author_absent_is_refused(directory: str, subject: str) -> None:
    with pytest.raises(EventError, match="auteur absent"):
        EventAuthor(directory, subject)


def test_object_ref_rejects_invalid_kind_and_empty_id() -> None:
    with pytest.raises(EventError, match="type d'objet"):
        ObjectRef("Groupe!", "g1")
    with pytest.raises(EventError, match="identifiant"):
        ObjectRef("group", "")


def _history_row(sequence: int) -> dict[str, Any]:
    return {
        "id": f"id-{sequence}",
        "type": "group.created",
        "functional_at": NOW,
        "functional_at_source": "caller",
        "written_at": NOW,
        "author_directory": "local",
        "author_subject": "admin",
        "properties": '{"k": 1}',
        "sequence": sequence,
    }


async def test_object_history_reports_missing_sequence_numbers() -> None:
    db = _FakeEventDb(history=[_history_row(1), _history_row(2), _history_row(4)])

    history = await db_object_history(db, ObjectRef("group", "g1"))

    assert [e.sequences[ObjectRef("group", "g1")] for e in history.events] == [1, 2, 4]
    assert history.missing_sequences == [3]
    assert history.events[0].properties == {"k": 1}


async def test_object_history_of_unknown_object_is_empty_without_gaps() -> None:
    history = await db_object_history(_FakeEventDb(), ObjectRef("group", "inconnu"))

    assert history.events == [] and history.missing_sequences == []
