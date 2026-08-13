"""FASE 9 — Transactional atomicity: ONE COMMAND = ONE TRANSACTION.

A failure during the second write must never leave partial state:
  aggregate A unchanged, B unchanged, no event persisted, command NOT marked
  as processed. Verified with injected failures.
"""

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    CreateOrUpdateMatchCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    CreateOrUpdateMatchHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.infrastructure.persistence.repositories import (
    SqliteCorrectionRepository,
    SqliteIdempotencyRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)
from feb_score.domain.errors import InvalidCorrection
from feb_score.domain.value_objects import ExternalId

from sqlite_helpers import cmd, finalized_match, make_player, make_team, proposal, register_command


class FailingMatchRepository(SqliteMatchRepository):
    """Raises on save once the correction was already applied (second write)."""

    def save(self, match):
        if match.correction_history:
            raise RuntimeError("injected failure on match save")
        super().save(match)


class FailingTeamRepository(SqliteTeamRepository):
    def save(self, team):
        raise RuntimeError("injected failure on team save")


def test_approve_correction_rolls_back_when_second_write_fails(sqlite_db):
    match_repo = SqliteMatchRepository(sqlite_db)
    correction_repo = SqliteCorrectionRepository(sqlite_db)
    idem_repo = SqliteIdempotencyRepository(sqlite_db)

    match = finalized_match()
    match_repo.save(match)
    p = proposal()
    correction_repo.save(p)

    failing_match_repo = FailingMatchRepository(sqlite_db)
    handler = ApproveCorrectionHandler(correction_repo, failing_match_repo, idem_repo)
    command = ApproveCorrectionCommand(**cmd({
        "proposal_id": p.proposal_id.value,
        "approved_by": {"id": "admin-1", "role": "admin"},
        "approved_at": "2026-02-02T12:00:00Z",
    }, role="admin"))

    with pytest.raises(RuntimeError):
        with sqlite_db.unit_of_work() as uow:
            events = handler.handle(command)
            uow.append_events(events)

    # proposal unchanged: still PROPOSED, nothing approved
    stored_proposal = correction_repo.get_by_id(p.proposal_id.value)
    assert stored_proposal.status == "PROPOSED"
    assert stored_proposal.approved_at is None
    # match unchanged: version intact, no correction applied
    stored_match = match_repo.get_by_external_id(ExternalId("2513600"))
    assert stored_match.version == match.version
    assert stored_match.correction_history == []
    assert stored_match.score_summary.home_score == 80
    # command NOT marked as processed
    assert not idem_repo.has_processed(command.command_id)


def test_register_player_rolls_back_when_second_write_fails(sqlite_db):
    player_repo = SqlitePlayerRepository(sqlite_db)
    team_repo = SqliteTeamRepository(sqlite_db)
    player_repo.save(make_player())
    team_repo.save(make_team())

    failing_team_repo = FailingTeamRepository(sqlite_db)
    handler = RegisterPlayerToSquadHandler(player_repo, failing_team_repo)
    command = RegisterPlayerToSquadCommand(**cmd(register_command(), role="admin"))

    with pytest.raises(RuntimeError):
        with sqlite_db.unit_of_work() as uow:
            handler.handle(command)

    stored_player = player_repo.get_by_external_id(ExternalId("pl-987"))
    stored_team = team_repo.get_by_external_id(ExternalId("team-123"))
    assert stored_player.registrations == []
    assert stored_team.registrations == []


def test_event_append_failure_rolls_back_aggregate_and_idempotency(sqlite_db):
    """Even a failure while persisting events rolls back the whole command."""
    match_repo = SqliteMatchRepository(sqlite_db)
    idem_repo = SqliteIdempotencyRepository(sqlite_db)
    handler = CreateOrUpdateMatchHandler(match_repo, idem_repo)
    command = CreateOrUpdateMatchCommand(**cmd({
        "external_id": "2513600", "competition_id": "feb-comp", "season_code": "2025-2026",
        "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }))

    with pytest.raises(AttributeError):
        with sqlite_db.unit_of_work() as uow:
            events = handler.handle(command)
            uow.append_events(events + [{"broken": "not-a-domain-event"}])

    assert match_repo.get_by_external_id(ExternalId("2513600")) is None
    assert not idem_repo.has_processed(command.command_id)


def test_approve_correction_domain_failure_persists_nothing(sqlite_db):
    """A domain rejection (unsupported op) inside the transaction leaves no state."""
    match_repo = SqliteMatchRepository(sqlite_db)
    correction_repo = SqliteCorrectionRepository(sqlite_db)
    match_repo.save(finalized_match())
    p = proposal(changes=[{"op": "add_event", "event": {"minute": 34}}])
    correction_repo.save(p)

    handler = ApproveCorrectionHandler(correction_repo, match_repo)
    command = ApproveCorrectionCommand(**cmd({
        "proposal_id": p.proposal_id.value,
        "approved_by": {"id": "admin-1", "role": "admin"},
        "approved_at": "2026-02-02T12:00:00Z",
    }, role="admin"))

    with pytest.raises(InvalidCorrection):
        with sqlite_db.unit_of_work() as uow:
            handler.handle(command)

    stored_proposal = correction_repo.get_by_id(p.proposal_id.value)
    stored_match = match_repo.get_by_external_id(ExternalId("2513600"))
    assert stored_proposal.status == "PROPOSED"
    assert stored_match.version == 2
    assert stored_match.correction_history == []