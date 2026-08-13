"""FASE 9 — Event dispatcher: at-least-once delivery with retry.

Events are marked delivered ONLY after the publisher succeeds. A failing publish
leaves the event pending (delivered=0) so a later dispatch retries it. Pending
events survive a connection/process restart.
"""

import pytest

from feb_score.application.commands.commands import CreateOrUpdateMatchCommand
from feb_score.application.use_cases.handlers import CreateOrUpdateMatchHandler
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_dispatcher import RecordingPublisher, SyncEventDispatcher
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from sqlite_helpers import cmd, create_match_command, run


def _produce_match_event(db):
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(db))
    run(db, handler, CreateOrUpdateMatchCommand(**cmd(create_match_command())))


def test_dispatch_delivers_and_marks_delivered(sqlite_db):
    _produce_match_event(sqlite_db)
    dispatcher = SyncEventDispatcher(sqlite_db, RecordingPublisher())

    assert dispatcher.dispatch() == 1
    assert dispatcher.pending_count() == 0


def test_failed_publish_stays_pending_and_retry_succeeds(sqlite_db):
    _produce_match_event(sqlite_db)
    failing = RecordingPublisher(fail_on=0)
    dispatcher = SyncEventDispatcher(sqlite_db, failing)

    assert dispatcher.dispatch() == 0  # publish raised -> nothing marked delivered
    assert dispatcher.pending_count() == 1
    assert failing.published == []

    working = RecordingPublisher()
    retry = SyncEventDispatcher(sqlite_db, working)
    assert retry.dispatch() == 1
    assert retry.pending_count() == 0
    assert [type(e).__name__ for e in working.published] == ["MatchUpserted"]


def test_pending_events_survive_restart(sqlite_db, db_path):
    _produce_match_event(sqlite_db)

    fresh = SqliteDatabase(db_path)
    dispatcher = SyncEventDispatcher(fresh, RecordingPublisher())
    assert dispatcher.pending_count() == 1
    assert dispatcher.dispatch() == 1
    assert dispatcher.pending_count() == 0


def test_dispatch_stops_on_first_failure(sqlite_db):
    from feb_score.application.commands.commands import FinalizeMatchCommand
    from feb_score.application.use_cases.handlers import FinalizeMatchHandler
    from feb_score.infrastructure.persistence.repositories import SqliteIdempotencyRepository

    from sqlite_helpers import ready_to_finalize

    match_repo = SqliteMatchRepository(sqlite_db)
    match_repo.save(ready_to_finalize())
    run(sqlite_db, FinalizeMatchHandler(match_repo, SqliteIdempotencyRepository(sqlite_db)),
        FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin")))

    dispatcher = SyncEventDispatcher(sqlite_db, RecordingPublisher(fail_on=0))
    assert dispatcher.dispatch() == 0
    assert dispatcher.pending_count() == 3  # Started + Validated + Finalized, all pending