"""FASE 7 — Idempotency integration tests.

Second attempt of the same command_id must not duplicate state or events when an
IdempotencyRepository is wired. Commands without an idempotency repo rely on
domain invariants to prevent duplication.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    FinalizeMatchCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.repositories.in_memory import (
    InMemoryCorrectionRepository,
    InMemoryIdempotencyRepository,
    InMemoryLeaderboardRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.domain.errors import InvalidPlayerRegistration
from feb_score.domain.value_objects import Actor, CommandMeta, ExternalId

from helpers import finalized_match, make_player, make_team, proposed_correction, scheduled_match


def cmd(payload, role="system", command_id=None):
    return dict(
        command_id=command_id or str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="actor-1", role=role),
        payload=payload,
    )


def test_create_or_update_match_replay_is_idempotent():
    repo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    handler = CreateOrUpdateMatchHandler(repo, idem)
    command = CreateOrUpdateMatchCommand(**cmd({
        "external_id": "2513600", "competition_id": "feb-competition", "season_code": "2025-2026",
        "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }))

    first = handler.handle(command)
    second = handler.handle(command)

    assert len(first) == 1
    assert second == []
    assert idem.has_processed(command.command_id)
    assert repo.get_by_external_id(ExternalId("2513600")) is not None


def test_finalize_match_replay_is_idempotent_and_does_not_reincrement_version():
    repo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    from feb_score.domain.statistics.model import TeamStats
    from feb_score.domain.value_objects import PeriodScore, ScoreSummary

    match = scheduled_match()
    match.score_summary = ScoreSummary(home_score=80, away_score=77, periods=(PeriodScore(1, 40, 38), PeriodScore(2, 40, 39)))
    match.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=80, points_against=77,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
        turnovers=10, rebounds=38,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=77, points_against=80,
        field_goals_made=28, field_goals_attempted=62, three_points_made=7,
        three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=34,
    )
    repo.save(match)

    handler = FinalizeMatchHandler(repo, idem)
    command = FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))

    first = handler.handle(command)
    second = handler.handle(command)

    assert any(e.__class__.__name__ == "MatchFinalized" for e in first)
    assert second == []
    stored = repo.get_by_external_id(ExternalId("2513600"))
    assert stored.status.value == "FINALIZED"
    assert stored.version == 2


def test_failed_finalize_is_not_marked_processed_and_retry_succeeds():
    repo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    from feb_score.domain.statistics.model import TeamStats
    from feb_score.domain.value_objects import PeriodScore, ScoreSummary

    match = scheduled_match()
    match.score_summary = None  # domain-invalid state
    repo.save(match)

    handler = FinalizeMatchHandler(repo, idem)
    command = FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))

    failed = handler.handle(command)
    assert any(e.__class__.__name__ == "ValidationFailed" for e in failed)
    assert not idem.has_processed(command.command_id)

    stored = repo.get_by_external_id(ExternalId("2513600"))
    stored.score_summary = ScoreSummary(home_score=80, away_score=77, periods=(PeriodScore(1, 40, 38), PeriodScore(2, 40, 39)))
    stored.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=80, points_against=77,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
        turnovers=10, rebounds=38,
    )
    stored.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=77, points_against=80,
        field_goals_made=28, field_goals_attempted=62, three_points_made=7,
        three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=34,
    )
    repo.save(stored)

    retried = handler.handle(command)
    assert any(e.__class__.__name__ == "MatchFinalized" for e in retried)
    assert idem.has_processed(command.command_id)


def test_propose_correction_replay_is_idempotent():
    crepo = InMemoryCorrectionRepository()
    idem = InMemoryIdempotencyRepository()
    handler = ProposeCorrectionHandler(crepo, idem)
    command = ProposeCorrectionCommand(**cmd({
        "match_external_id": "2513600", "proposed_by": {"id": "editor-1", "role": "editor"},
        "reason": "Official score correction",
        "changes": [{"op": "update_score", "home_score": 78, "away_score": 75}],
    }, role="editor"))

    first = handler.handle(command)
    second = handler.handle(command)
    assert first.payload["proposal_id"] == command.command_id
    assert second == []
    assert len(crepo._proposals) == 1


def test_approve_correction_replay_is_idempotent():
    crepo = InMemoryCorrectionRepository()
    mrepo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    mrepo.save(finalized_match())
    proposal_id = str(uuid4())
    crepo.save(proposed_correction(proposal_id))

    handler = ApproveCorrectionHandler(crepo, mrepo, idem)
    command = ApproveCorrectionCommand(**cmd({
        "proposal_id": proposal_id,
        "approved_by": {"id": "admin-1", "role": "admin"},
        "approved_at": "2026-02-02T12:00:00Z",
    }, role="admin"))

    first = handler.handle(command)
    second = handler.handle(command)
    assert len(first) == 2
    assert second == []
    stored = mrepo.get_by_external_id(ExternalId("2513600"))
    assert stored.version == 3
    assert len(stored.correction_history) == 1


def test_compute_rating_replay_is_idempotent():
    mrepo = InMemoryMatchRepository()
    rrepo = InMemoryRatingRepository()
    idem = InMemoryIdempotencyRepository()
    mrepo.save(finalized_match())

    handler = ComputePlayerRatingHandler(mrepo, rrepo, idem)
    command = ComputePlayerRatingCommand(**cmd({
        "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0",
    }))

    first = handler.handle(command)
    second = handler.handle(command)
    assert len(first) >= 1
    assert second == []
    assert len(rrepo._ratings) == 1


def test_generate_standing_replay_is_idempotent():
    srepo = InMemoryStandingRepository()
    mrepo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    mrepo.save(finalized_match())

    handler = GenerateStandingSnapshotHandler(srepo, mrepo, idem)
    command = GenerateStandingSnapshotCommand(**cmd({
        "competition_id": "unknown", "season_code": "2025-2026",
        "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
    }))

    first = handler.handle(command)
    second = handler.handle(command)
    assert first.__class__.__name__ == "StandingSnapshotGenerated"
    assert second == []
    assert len(srepo._standings) == 1


def test_generate_leaderboard_replay_is_idempotent():
    lrepo = InMemoryLeaderboardRepository()
    mrepo = InMemoryMatchRepository()
    idem = InMemoryIdempotencyRepository()
    mrepo.save(finalized_match())

    handler = GenerateLeaderboardHandler(mrepo, lrepo, idem)
    command = GenerateLeaderboardCommand(**cmd({
        "season_code": "2025-2026", "category": "points_per_game", "min_games": 0, "top_n": 10,
    }))

    first = handler.handle(command)
    second = handler.handle(command)
    assert first.__class__.__name__ == "LeaderboardGenerated"
    assert second == []
    assert len(lrepo._leaderboards) == 1


def test_register_player_replay_raises_without_duplicating():
    """RegisterPlayerToSquad has no idempotency repo; the domain invariant prevents duplicates."""
    prepo = InMemoryPlayerRepository()
    trepo = InMemoryTeamRepository()
    prepo.save(make_player())
    trepo.save(make_team())

    handler = RegisterPlayerToSquadHandler(prepo, trepo)
    payload = {
        "player_external_id": "pl-987", "team_external_id": "team-123", "season_code": "2025-2026",
        "dorsal": "12", "registered_from": "2025-08-01T00:00:00Z",
    }
    command = RegisterPlayerToSquadCommand(**cmd(payload, role="admin"))
    handler.handle(command)

    with pytest.raises(InvalidPlayerRegistration):
        handler.handle(command)

    assert len(prepo.get_by_external_id(ExternalId("pl-987")).registrations) == 1
    assert len(trepo.get_by_external_id(ExternalId("team-123")).registrations) == 1