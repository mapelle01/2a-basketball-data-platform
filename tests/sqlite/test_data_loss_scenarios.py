"""FASE 10 — Data-loss scenarios.

For each plausible crash window we pin down what SURVIVES (state/events/
idempotency) and what the recovery action is. The guarantees rest on:
  * one transaction per command (state + events + idempotency commit together);
  * outbox-lite: events are persisted in the command transaction, dispatched only
    AFTER commit (at-least-once);
  * optimistic locking: a crash can never produce a silent lost update.
"""

from feb_score.application.commands.commands import CreateOrUpdateMatchCommand
from feb_score.application.use_cases.handlers import CreateOrUpdateMatchHandler
from feb_score.domain.value_objects import ExternalId
from feb_score.infrastructure.persistence.event_dispatcher import (
    RecordingPublisher,
    SyncEventDispatcher,
)
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from sqlite_helpers import cmd, create_match_command, ready_to_finalize


def test_crash_before_commit_loses_nothing_partial(sqlite_db):
    """A failing command must not leave half-written state, events or idempotency."""
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))

    try:
        with sqlite_db.unit_of_work() as uow:
            handler.handle(command)  # state mutated in the transaction...
            uow.append_events([__import__("feb_score.domain.events", fromlist=["MatchUpserted"]).MatchUpserted(
                event_id="boom-event",
                meta=__import__("feb_score.domain.value_objects", fromlist=["EventMeta"]).EventMeta(
                    version="1.0", produced_at=__import__("datetime").datetime.utcnow()),
                source={}, payload={},
            )])
            raise RuntimeError("crash before commit")  # ...then the process dies
    except RuntimeError:
        pass

    assert SqliteMatchRepository(sqlite_db).get_by_external_id(ExternalId("2513600")) is None
    assert SqliteEventStore(sqlite_db).pending_count() == 0


def test_crash_after_commit_before_dispatch_redelivers_on_restart(sqlite_db):
    """Events committed but never dispatched survive a restart and are delivered."""
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))

    with sqlite_db.unit_of_work() as uow:
        result = handler.handle(command)
        uow.append_events(result if isinstance(result, list) else [result])
    # (no dispatch: the process dies right after commit)

    pending = SqliteEventStore(sqlite_db).pending_count()
    assert pending >= 1
    assert SqliteMatchRepository(sqlite_db).get_by_external_id(ExternalId("2513600")) is not None

    # Restart: a fresh dispatcher drains the outbox.
    publisher = RecordingPublisher()
    assert SyncEventDispatcher(sqlite_db, publisher).dispatch() == pending
    assert len(publisher.published) == pending


def test_crash_during_dispatch_redelivers_and_consumer_dedupes(sqlite_db):
    """Partial delivery + crash => redelivery; at-least-once is handled by the
    idempotent consumer, so downstream sees each event exactly once."""
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    with sqlite_db.unit_of_work() as uow:
        result = handler.handle(command)
        uow.append_events(result if isinstance(result, list) else [result])

    from feb_score.infrastructure.persistence.event_dispatcher import IdempotentConsumer

    raw = RecordingPublisher()
    dispatcher = SyncEventDispatcher(sqlite_db, IdempotentConsumer(raw))
    assert dispatcher.dispatch() >= 1

    # Simulate the crash window: event re-appears as pending (publish ok, mark lost).
    conn = sqlite_db.connect()
    try:
        conn.execute("UPDATE domain_events SET delivered = 0")
    finally:
        conn.close()
    assert dispatcher.dispatch() >= 1
    # every event delivered exactly once downstream
    published_ids = [e.event_id for e in raw.published]
    assert len(published_ids) == len(set(published_ids))


def test_retry_after_restart_is_idempotent_at_command_level(sqlite_db):
    """Replaying a command after a restart must not duplicate state (idempotency)."""
    from feb_score.application.commands.commands import CreateOrUpdateMatchCommand

    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    with sqlite_db.unit_of_work() as uow:
        result = handler.handle(command)
        uow.append_events(result if isinstance(result, list) else [result])

    # The same command (same command_id) is replayed after a restart.
    with sqlite_db.unit_of_work() as uow:
        result = handler.handle(command)
        uow.append_events(result if isinstance(result, list) else [result])

    matches = list(SqliteMatchRepository(sqlite_db).list_by_season("feb-comp", "2025-2026"))
    assert len(matches) == 1  # not duplicated


def test_concurrent_double_finalize_yields_no_lost_update(sqlite_db):
    """Optimistic locking: even if two writers race, the loser is rejected loudly."""
    from feb_score.infrastructure.persistence.errors import StaleVersionError
    from datetime import datetime

    repo = SqliteMatchRepository(sqlite_db)
    match = ready_to_finalize()
    repo.save(match)

    a = repo.get_by_external_id(match.external_id)
    b = repo.get_by_external_id(match.external_id)
    a.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    repo.save(a)
    b.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    try:
        repo.save(b)
        rejected = False
    except StaleVersionError:
        rejected = True
    assert rejected
    assert repo.get_by_external_id(match.external_id).status.value == "FINALIZED"