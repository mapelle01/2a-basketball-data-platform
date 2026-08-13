"""FASE 10 — Event dispatcher hardening: ordering, at-least-once, dedup, retry."""

from datetime import datetime
from uuid import uuid4

from feb_score.domain.events import MatchUpserted
from feb_score.domain.value_objects import EventMeta
from feb_score.infrastructure.persistence.event_dispatcher import (
    IdempotentConsumer,
    RecordingPublisher,
    SyncEventDispatcher,
)
from feb_score.infrastructure.persistence.event_store import SqliteEventStore


def _evt(produced_at):
    return MatchUpserted(
        event_id=str(uuid4()),
        meta=EventMeta(version="1.0", produced_at=produced_at),
        source={"command_id": str(uuid4())},
        payload={"external_id": "2513600"},
    )


def test_events_delivered_in_produced_order(sqlite_db):
    store = SqliteEventStore(sqlite_db)
    e1 = _evt(datetime(2026, 2, 1, 9, 0, 0))
    e2 = _evt(datetime(2026, 2, 1, 8, 0, 0))
    e3 = _evt(datetime(2026, 2, 1, 10, 0, 0))
    store.append_many([e1, e2, e3])

    pub = RecordingPublisher()
    dispatcher = SyncEventDispatcher(sqlite_db, pub)
    assert dispatcher.dispatch() == 3
    assert [e.event_id for e in pub.published] == [e2.event_id, e1.event_id, e3.event_id]
    assert dispatcher.pending_count() == 0


def test_crash_between_publish_and_mark_redelivers_but_consumer_dedupes(sqlite_db):
    store = SqliteEventStore(sqlite_db)
    store.append_many([_evt(datetime(2026, 2, 1, 8, 0, 0))])

    raw = RecordingPublisher()
    consumer = IdempotentConsumer(raw)
    dispatcher = SyncEventDispatcher(sqlite_db, consumer)
    assert dispatcher.dispatch() == 1
    assert len(raw.published) == 1

    # Simulate a crash AFTER the publisher returned but BEFORE the delivered mark:
    # the event is pending again and will be redelivered on the next dispatch.
    conn = sqlite_db.connect()
    try:
        conn.execute("UPDATE domain_events SET delivered = 0")
    finally:
        conn.close()
    assert dispatcher.pending_count() == 1
    assert dispatcher.dispatch() == 1
    # downstream consumer observed the event exactly once (at-least-once safe)
    assert len(raw.published) == 1
    assert dispatcher.pending_count() == 0


def test_publish_failure_keeps_pending_and_restart_retries(sqlite_db):
    store = SqliteEventStore(sqlite_db)
    store.append_many([_evt(datetime(2026, 2, 1, 8, 0, 0)), _evt(datetime(2026, 2, 1, 9, 0, 0))])

    failing = SyncEventDispatcher(sqlite_db, RecordingPublisher(fail_on=0))
    assert failing.dispatch() == 0
    assert failing.pending_count() == 2

    # A fresh dispatcher (process restart) with a healthy consumer drains the queue.
    healthy_pub = RecordingPublisher()
    healthy = SyncEventDispatcher(sqlite_db, healthy_pub)
    assert healthy.dispatch() == 2
    assert len(healthy_pub.published) == 2
    assert failing.pending_count() == 0


def test_dispatch_limit_respected(sqlite_db):
    store = SqliteEventStore(sqlite_db)
    store.append_many([_evt(datetime(2026, 2, 1, 8, 0, 0)) for _ in range(5)])
    pub = RecordingPublisher()
    dispatcher = SyncEventDispatcher(sqlite_db, pub)
    assert dispatcher.dispatch(limit=3) == 3
    assert len(pub.published) == 3
    assert dispatcher.pending_count() == 2