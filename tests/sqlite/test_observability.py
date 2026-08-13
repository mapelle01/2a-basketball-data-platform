"""FASE 10 — Observability: CommandRunner logs a traceable command lifecycle."""

import pytest

from feb_score.application.commands.commands import (
    CreateOrUpdateMatchCommand,
    FinalizeMatchCommand,
)
from feb_score.application.use_cases.handlers import (
    CreateOrUpdateMatchHandler,
    FinalizeMatchHandler,
)
from feb_score.domain.errors import MatchNotFound
from feb_score.infrastructure.application_service import CommandRunner
from feb_score.infrastructure.logging import RecordingLogger, StdLogger
from feb_score.infrastructure.persistence.event_dispatcher import (
    RecordingPublisher,
    SyncEventDispatcher,
)
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from sqlite_helpers import cmd, create_match_command


def test_command_lifecycle_is_logged(sqlite_db):
    logger = RecordingLogger()
    runner = CommandRunner(sqlite_db, logger=logger)
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))

    runner.run(handler, CreateOrUpdateMatchCommand(**cmd(create_match_command())))

    assert logger.has("command_started", "info")
    assert logger.has("command_completed", "info")
    started = logger.messages("command_started")[0]
    assert started[2]["command"] == "CreateOrUpdateMatchCommand"


def test_events_and_dispatch_are_logged(sqlite_db):
    logger = RecordingLogger()
    publisher = RecordingPublisher()
    dispatcher = SyncEventDispatcher(sqlite_db, publisher, logger=logger)
    runner = CommandRunner(sqlite_db, dispatcher=dispatcher, logger=logger)
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))

    runner.run(handler, CreateOrUpdateMatchCommand(**cmd(create_match_command())))

    assert logger.has("command_completed", "info")
    assert logger.has("dispatch_completed", "info")
    assert logger.has("event_published", "info")
    assert len(publisher.published) >= 1
    completed = logger.messages("command_completed")[0]
    assert completed[2]["events"] >= 1


def test_failure_is_logged_and_reraised_and_rolls_back(sqlite_db):
    logger = RecordingLogger()
    runner = CommandRunner(sqlite_db, logger=logger)
    repo = SqliteMatchRepository(sqlite_db)

    # Finalizing a match that does not exist raises MatchNotFound from the handler.
    handler = FinalizeMatchHandler(repo)
    command = FinalizeMatchCommand(
        **cmd({"match_external_id": "does-not-exist", "validation_context": {"strict": True}}, role="admin")
    )
    with pytest.raises(MatchNotFound):
        runner.run(handler, command)

    assert logger.has("command_failed", "error")
    assert logger.messages("command_failed")[0][2]["error"] == "MatchNotFound"
    # failed command persisted nothing
    assert SqliteEventStore(sqlite_db).pending_count() == 0


def test_std_logger_writes_structured_fields(capsys):
    StdLogger("feb_score.capsys.test").log("info", "command_started", command="X", command_id="c1")
    err = capsys.readouterr().err
    assert "command_started" in err
    assert "command=X" in err
    assert "command_id=c1" in err


def test_publish_failure_logs_dispatch_failed_and_stays_pending(sqlite_db):
    """F-04: a failed publish is logged as dispatch_failed (event_id, event_type,
    classified error) and the event is NOT marked delivered (at-least-once)."""
    logger = RecordingLogger()
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    CommandRunner(sqlite_db, logger=logger).run(
        handler, CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    )
    assert SqliteEventStore(sqlite_db).pending_count() == 1

    dispatcher = SyncEventDispatcher(
        sqlite_db, RecordingPublisher(fail_on=0), logger=logger
    )
    assert dispatcher.dispatch() == 0
    assert logger.has("dispatch_failed", "error")
    record = logger.messages("dispatch_failed")[0]
    fields = record[2]
    assert fields["event_id"]
    assert fields["event_type"] == "MatchUpserted"
    assert fields["error"] == "RuntimeError"
    assert "Injected publish failure" in fields.get("error_message", "")
    assert SqliteEventStore(sqlite_db).pending_count() == 1


def test_corrupt_event_logs_dispatch_failed_and_stays_pending(sqlite_db):
    """F-04: an unprocessable event row aborts dispatch loudly (error log) and
    stays pending instead of being marked delivered or crashing the caller."""
    logger = RecordingLogger()
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    CommandRunner(sqlite_db, logger=logger).run(
        handler, CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    )
    assert SqliteEventStore(sqlite_db).pending_count() == 1

    conn = sqlite_db.connect()
    conn.execute("UPDATE domain_events SET payload = '{\"broken\"' WHERE delivered = 0")
    conn.close()

    dispatcher = SyncEventDispatcher(sqlite_db, RecordingPublisher(), logger=logger)
    assert dispatcher.dispatch() == 0
    assert logger.has("dispatch_failed", "error")
    fields = logger.messages("dispatch_failed")[0][2]
    assert fields["event_type"] == "MatchUpserted"
    assert fields["error"]
    assert SqliteEventStore(sqlite_db).pending_count() == 1