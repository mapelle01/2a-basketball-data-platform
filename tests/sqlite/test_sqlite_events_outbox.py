"""FASE 9 — Domain events / outbox-lite persistence.

A successful command must persist aggregate state + events + idempotency in ONE
transaction. A failed command must persist NONE of the three. Events survive a
connection/process restart and remain undelivered until dispatched.
"""

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    CreateOrUpdateMatchCommand,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    CreateOrUpdateMatchHandler,
)
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_store import SqliteEventStore, reconstruct_event
from feb_score.infrastructure.persistence.repositories import (
    SqliteCorrectionRepository,
    SqliteIdempotencyRepository,
    SqliteMatchRepository,
)
from feb_score.domain.value_objects import ExternalId

from sqlite_helpers import cmd, create_match_command, finalized_match, proposal, run


def test_successful_command_persists_state_events_and_idempotency_together(sqlite_db):
    match_repo = SqliteMatchRepository(sqlite_db)
    idem = SqliteIdempotencyRepository(sqlite_db)
    handler = CreateOrUpdateMatchHandler(match_repo, idem)
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))

    run(sqlite_db, handler, command)

    assert match_repo.get_by_external_id(ExternalId("2513600")) is not None
    assert SqliteEventStore(sqlite_db).pending_count() == 1
    assert idem.has_processed(command.command_id)


def test_failed_command_persists_nothing(sqlite_db):
    match_repo = SqliteMatchRepository(sqlite_db)
    idem = SqliteIdempotencyRepository(sqlite_db)
    handler = CreateOrUpdateMatchHandler(match_repo, idem)
    # home_team_id == away_team_id violates a domain invariant inside the handler
    payload = create_match_command()
    payload["home_team"] = {"external_id": "same", "name": "A"}
    payload["away_team"] = {"external_id": "same", "name": "B"}
    command = CreateOrUpdateMatchCommand(**cmd(payload))

    with pytest.raises(ValueError):
        run(sqlite_db, handler, command)

    assert match_repo.get_by_external_id(ExternalId("2513600")) is None
    assert SqliteEventStore(sqlite_db).pending_count() == 0
    assert not idem.has_processed(command.command_id)


def test_events_survive_restart_and_are_reconstructable(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    handler = CreateOrUpdateMatchHandler(match_repo, None)
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    run(sqlite_db, handler, command)

    fresh = SqliteDatabase(db_path)
    store = SqliteEventStore(fresh)
    assert store.pending_count() == 1

    row = store.fetch_undelivered()[0]
    assert row["event_type"] == "MatchUpserted"
    event = reconstruct_event(row)
    assert event.payload["external_id"] == "2513600"
    assert event.meta.produced_at is not None


def test_approve_correction_persists_two_events_in_one_transaction(sqlite_db):
    match_repo = SqliteMatchRepository(sqlite_db)
    correction_repo = SqliteCorrectionRepository(sqlite_db)
    match_repo.save(finalized_match())
    p = proposal()
    correction_repo.save(p)

    handler = ApproveCorrectionHandler(correction_repo, match_repo)
    command = ApproveCorrectionCommand(**cmd({
        "proposal_id": p.proposal_id.value,
        "approved_by": {"id": "admin-1", "role": "admin"},
        "approved_at": "2026-02-02T12:00:00Z",
    }, role="admin"))

    run(sqlite_db, handler, command)

    store = SqliteEventStore(sqlite_db)
    rows = store.fetch_undelivered()
    assert {r["event_type"] for r in rows} == {"MatchUpdatedByCorrection", "CorrectionApproved"}