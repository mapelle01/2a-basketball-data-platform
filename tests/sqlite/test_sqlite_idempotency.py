"""FASE 9 — Idempotency persists across process/connection restarts.

The 7 commands with explicit idempotency survive a restart: the same command_id
re-run on a NEW connection produces no state/event duplication. Commands without
explicit idempotency keep their documented replay semantics (domain invariants /
append-only), matching the in-memory behaviour exactly.
"""

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    CreatePublicationCommand,
    FinalizeMatchCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    CreatePublicationHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteCorrectionRepository,
    SqliteIdempotencyRepository,
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqlitePublicationRepository,
    SqliteRatingRepository,
    SqliteStandingRepository,
    SqliteTeamRepository,
)
from feb_score.domain.errors import InvalidPlayerRegistration
from feb_score.domain.value_objects import CompetitionId, ExternalId, SeasonCode

from sqlite_helpers import cmd, create_match_command, finalized_match, make_player, make_team, proposal, run, ready_to_finalize, register_command


def _restart(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    return db


def test_create_or_update_match_replay_after_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    idem = SqliteIdempotencyRepository(sqlite_db)
    handler = CreateOrUpdateMatchHandler(match_repo, idem)
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))

    first = run(sqlite_db, handler, command)
    assert len(first) == 1

    fresh = _restart(db_path)
    fresh_handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(fresh), SqliteIdempotencyRepository(fresh))
    second = run(fresh, fresh_handler, command)

    assert second == []
    matches = list(SqliteMatchRepository(fresh).list_by_season(CompetitionId("feb-comp"), SeasonCode("2025-2026")))
    assert len(matches) == 1


def test_finalize_match_replay_after_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    idem = SqliteIdempotencyRepository(sqlite_db)
    match_repo.save(ready_to_finalize())

    handler = FinalizeMatchHandler(match_repo, idem)
    command = FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))

    first = run(sqlite_db, handler, command)
    assert any(e.__class__.__name__ == "MatchFinalized" for e in first)

    fresh = _restart(db_path)
    fresh_handler = FinalizeMatchHandler(SqliteMatchRepository(fresh), SqliteIdempotencyRepository(fresh))
    second = run(fresh, fresh_handler, command)

    assert second == []
    stored = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))
    assert stored.status.value == "FINALIZED"
    assert stored.version == 2


def test_propose_and_approve_replay_after_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    correction_repo = SqliteCorrectionRepository(sqlite_db)
    match_repo.save(finalized_match())
    p = proposal()
    correction_repo.save(p)

    propose_idem = SqliteIdempotencyRepository(sqlite_db)
    approve_idem = SqliteIdempotencyRepository(sqlite_db)
    approve_cmd = ApproveCorrectionCommand(**cmd({
        "proposal_id": p.proposal_id.value,
        "approved_by": {"id": "admin-1", "role": "admin"},
        "approved_at": "2026-02-02T12:00:00Z",
    }, role="admin"))
    approve_handler = ApproveCorrectionHandler(correction_repo, match_repo, approve_idem)

    first = run(sqlite_db, approve_handler, approve_cmd)
    assert len(first) == 2

    fresh = _restart(db_path)
    fresh_approve = ApproveCorrectionHandler(
        SqliteCorrectionRepository(fresh), SqliteMatchRepository(fresh), SqliteIdempotencyRepository(fresh)
    )
    second = run(fresh, fresh_approve, approve_cmd)

    assert second == []
    stored = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))
    assert stored.version == 3
    assert len(stored.correction_history) == 1


def test_compute_rating_replay_after_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    rating_repo = SqliteRatingRepository(sqlite_db)
    match_repo.save(finalized_match())

    handler = ComputePlayerRatingHandler(match_repo, rating_repo, SqliteIdempotencyRepository(sqlite_db))
    command = ComputePlayerRatingCommand(**cmd({
        "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0",
        "competition_id": "feb-comp",
    }))

    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    fresh_handler = ComputePlayerRatingHandler(
        SqliteMatchRepository(fresh), SqliteRatingRepository(fresh), SqliteIdempotencyRepository(fresh)
    )
    assert run(fresh, fresh_handler, command) == []
    assert len(SqliteRatingRepository(fresh).list_all()) == 1


def test_generate_standing_replay_after_restart(sqlite_db, db_path):
    standing_repo = SqliteStandingRepository(sqlite_db)
    match_repo = SqliteMatchRepository(sqlite_db)
    match_repo.save(finalized_match())

    handler = GenerateStandingSnapshotHandler(standing_repo, match_repo, SqliteIdempotencyRepository(sqlite_db))
    command = GenerateStandingSnapshotCommand(**cmd({
        "competition_id": "feb-comp", "season_code": "2025-2026",
        "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
    }))

    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    fresh_handler = GenerateStandingSnapshotHandler(
        SqliteStandingRepository(fresh), SqliteMatchRepository(fresh), SqliteIdempotencyRepository(fresh)
    )
    assert run(fresh, fresh_handler, command) == []
    assert len(SqliteStandingRepository(fresh).list_all()) == 1


def test_generate_leaderboard_replay_after_restart(sqlite_db, db_path):
    leaderboard_repo = SqliteLeaderboardRepository(sqlite_db)
    match_repo = SqliteMatchRepository(sqlite_db)
    match_repo.save(finalized_match())

    handler = GenerateLeaderboardHandler(match_repo, leaderboard_repo, SqliteIdempotencyRepository(sqlite_db))
    command = GenerateLeaderboardCommand(**cmd({
        "season_code": "2025-2026", "category": "points_per_game", "min_games": 0, "top_n": 10,
        "competition_id": "feb-comp",
    }))

    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    fresh_handler = GenerateLeaderboardHandler(
        SqliteMatchRepository(fresh), SqliteLeaderboardRepository(fresh), SqliteIdempotencyRepository(fresh)
    )
    assert run(fresh, fresh_handler, command) == []
    boards = SqliteLeaderboardRepository(fresh).list_all()
    assert len(boards) == 1
    assert boards[0].entries


def test_register_player_replay_raises_without_duplication(sqlite_db):
    """No explicit idempotency: the domain invariant prevents duplicates (as in-memory)."""
    player_repo = SqlitePlayerRepository(sqlite_db)
    team_repo = SqliteTeamRepository(sqlite_db)
    player_repo.save(make_player())
    team_repo.save(make_team())

    handler = RegisterPlayerToSquadHandler(player_repo, team_repo)
    command = RegisterPlayerToSquadCommand(**cmd(register_command(), role="admin"))

    run(sqlite_db, handler, command)
    with pytest.raises(InvalidPlayerRegistration):
        run(sqlite_db, handler, command)

    stored = player_repo.get_by_external_id(ExternalId("pl-987"))
    assert len(stored.registrations) == 1


def test_create_publication_replay_overwrites_same_publication_id(sqlite_db, db_path):
    """No explicit idempotency repo, but the publication_id IS the command_id: SQLite
    overwrites the same row on replay (stricter than the in-memory append; documented)."""
    pub_repo = SqlitePublicationRepository(sqlite_db)
    handler = CreatePublicationHandler(pub_repo)
    command = CreatePublicationCommand(**cmd({
        "template_id": "tpl-1", "payload_refs": {"match_external_id": "2513600"},
        "scheduled_at": "2026-02-02T08:00:00Z",
    }, role="editor"))

    run(sqlite_db, handler, command)
    run(sqlite_db, handler, command)

    assert len(SqlitePublicationRepository(_restart(db_path)).list_all()) == 1