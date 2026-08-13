"""FASE 9 — Application integration: FASE 7 flows executed with real SQLite
repositories, verified across a connection/process restart (new SqliteDatabase).
"""

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    FinalizeMatchCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
)
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteCorrectionRepository,
    SqliteIdempotencyRepository,
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqliteRatingRepository,
    SqliteStandingRepository,
)
from feb_score.domain.value_objects import ExternalId

from sqlite_helpers import cmd, create_match_command, finalized_match, proposal, ready_to_finalize, run


def _restart(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    return db


def test_create_match_persists_across_restart(sqlite_db, db_path):
    handler = CreateOrUpdateMatchHandler(SqliteMatchRepository(sqlite_db))
    command = CreateOrUpdateMatchCommand(**cmd(create_match_command()))
    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    loaded = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))
    assert loaded is not None
    assert loaded.status.value == "SCHEDULED"
    assert loaded.scheduled_at.isoformat() == "2026-02-01T18:30:00"


def test_finalize_match_persists_across_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    match_repo.save(ready_to_finalize())
    handler = FinalizeMatchHandler(match_repo)
    command = FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))
    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    loaded = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))
    assert loaded.status.value == "FINALIZED"
    assert loaded.score_summary.home_score == 80
    assert loaded.version == 2


def test_correction_persists_both_aggregates_across_restart(sqlite_db, db_path):
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

    fresh = _restart(db_path)
    fresh_proposal = SqliteCorrectionRepository(fresh).get_by_id(p.proposal_id.value)
    fresh_match = SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600"))
    assert fresh_proposal.status == "APPROVED"
    assert fresh_match.version == 3
    assert len(fresh_match.correction_history) == 1
    assert fresh_match.score_summary.home_score == 80


def test_rating_persists_across_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    rating_repo = SqliteRatingRepository(sqlite_db)
    match_repo.save(finalized_match())
    handler = ComputePlayerRatingHandler(match_repo, rating_repo)
    command = ComputePlayerRatingCommand(**cmd({
        "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0",
        "competition_id": "feb-comp",
    }))
    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    ratings = SqliteRatingRepository(fresh).list_all()
    assert len(ratings) == 1
    assert round(ratings[0].rating_value.value, 2) == round(22 * 1.0 + 9 * 1.2 + 5 * 1.5 - 2 * 0.8, 2)
    assert ratings[0].source_stats[0]["played_at"] == "2026-02-01T18:30:00"


def test_leaderboard_persists_across_restart(sqlite_db, db_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    leaderboard_repo = SqliteLeaderboardRepository(sqlite_db)
    match_repo.save(finalized_match())
    handler = GenerateLeaderboardHandler(match_repo, leaderboard_repo)
    command = GenerateLeaderboardCommand(**cmd({
        "season_code": "2025-2026", "category": "points_per_game", "min_games": 0, "top_n": 10,
        "competition_id": "feb-comp",
    }))
    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    boards = SqliteLeaderboardRepository(fresh).list_all()
    assert len(boards) == 1
    assert boards[0].entries[0].player_external_id == "pl-1"
    assert boards[0].entries[0].value == 22.0


def test_standing_snapshot_persists_across_restart(sqlite_db, db_path):
    standing_repo = SqliteStandingRepository(sqlite_db)
    match_repo = SqliteMatchRepository(sqlite_db)
    match_repo.save(finalized_match())
    handler = GenerateStandingSnapshotHandler(standing_repo, match_repo)
    command = GenerateStandingSnapshotCommand(**cmd({
        "competition_id": "feb-comp", "season_code": "2025-2026",
        "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
    }))
    run(sqlite_db, handler, command)

    fresh = _restart(db_path)
    snapshots = SqliteStandingRepository(fresh).list_all()
    assert len(snapshots) == 1
    assert snapshots[0].matches_count == 1
    team_home = next(e for e in snapshots[0].entries if e.team_external_id == "team-home")
    assert team_home.points == 2