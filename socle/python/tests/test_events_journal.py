from __future__ import annotations

import json
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from miles_socle.events.history import db_object_history
from miles_socle.events.journal import db_write_event, db_write_events
from miles_socle.events.model import (
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
        self.savepoints = 0

    def is_in_transaction(self) -> bool:
        return self.in_transaction

    @asynccontextmanager
    async def transaction(self) -> Any:
        # Le point de sauvegarde de la vraie connexion. La doublure n'échoue jamais sur une
        # partition manquante : c'est un défaut de BASE, et il s'éprouve sur une base réelle
        # (tests d'intégration des trois produits), pas sur une doublure qui dirait oui.
        self.savepoints += 1
        yield None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "event_object_sequences" in query:
            # La doublure rend ce que rend la vraie instruction : UNE ligne par objet
            # distinct, portant le DERNIER numéro attribué — soit l'ancien plus le nombre
            # d'occurrences du lot. Compter un par ligne reçue ferait croire au code
            # appelant que ses numéros sont contigus alors qu'ils se chevaucheraient.
            occurrences = Counter(zip(args[0], args[1], strict=True))
            rows = []
            for (kind, object_id), combien in occurrences.items():
                value = self.counters.get((kind, object_id), 0) + combien
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
    proprietes, instant = db.executed[0][1][-2], db.executed[0][1][-1]
    assert [json.loads(p) for p in proprietes] == [{"group": "g1"}]
    assert instant == NOW
    # Les objets sont envoyés triés : ordre de verrouillage fixe.
    assert db.executed[1][1][0] == ["device", "group"]


async def test_write_events_writes_a_whole_batch_in_three_statements() -> None:
    """Le point de l'écriture ensembliste : le nombre d'instructions ne suit pas N."""
    db = _FakeEventDb()
    lot = [_event(objects=(ObjectRef("group", f"g{rang}"),)) for rang in range(50)]

    ecrits = await db_write_events(db, lot, CATALOG, lambda: NOW)

    assert len(ecrits) == 50
    # Une réservation de numéros, puis l'insertion des events et celle de leurs liens.
    assert len(db.executed) == 2
    assert len(db.executed[0][1][0]) == 50 and len(db.executed[1][1][0]) == 50


async def test_write_events_numbers_an_object_touched_twice_contiguously() -> None:
    """Deux events du MÊME lot sur le même objet : des numéros qui se suivent.

    C'est le cas que l'ancienne instruction ne savait pas écrire — deux lignes de même
    clé dans un `ON CONFLICT DO UPDATE` font échouer l'instruction entière.
    """
    db = _FakeEventDb()
    db.counters[("group", "g1")] = 4
    lot = [_event(properties={"n": 1}), _event(properties={"n": 2})]

    ecrits = await db_write_events(db, lot, CATALOG, lambda: NOW)

    assert [e.sequences[ObjectRef("group", "g1")] for e in ecrits] == [5, 6]
    assert db.executed[1][1][2] == [5, 6]


async def test_write_events_of_an_empty_batch_writes_nothing() -> None:
    """« Rien à tracer » est le cas normal d'un import dont aucun objet n'a changé."""
    db = _FakeEventDb()

    assert await db_write_events(db, [], CATALOG, lambda: NOW) == []
    assert db.executed == [] and db.counters == {}


async def test_write_events_share_one_written_at() -> None:
    """Écrits par la même transaction, donc observables au même instant — et dans la même
    partition, ce qu'un instant par event ne garantit pas à la frontière d'une journée."""
    instants = iter([NOW, NOW + timedelta(hours=1)])
    lot = [_event(), _event(objects=(ObjectRef("group", "g2"),))]

    ecrits = await db_write_events(_FakeEventDb(), lot, CATALOG, lambda: next(instants))

    assert {e.written_at for e in ecrits} == {NOW}


async def test_write_events_outside_transaction_is_refused() -> None:
    db = _FakeEventDb(in_transaction=False)

    with pytest.raises(EventError, match="transaction"):
        await db_write_events(db, [_event()], CATALOG, lambda: NOW)

    assert db.executed == []


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
