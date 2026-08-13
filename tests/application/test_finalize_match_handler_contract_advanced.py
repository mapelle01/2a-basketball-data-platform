from datetime import datetime
from uuid import uuid4
import pytest
from unittest.mock import patch

from feb_score.application.commands.commands import FinalizeMatchCommand
from feb_score.application.repositories.in_memory import InMemoryMatchRepository
from feb_score.application.use_cases.handlers import FinalizeMatchHandler
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import TeamStats, PlayerStats
from feb_score.domain.value_objects import Actor, CommandMeta, CompetitionId, ExternalId, MatchId, SeasonCode, ScoreSummary, PeriodScore

def setup_match(match_repo, match_external_id="2513600"):
    match = Match(
        external_id=ExternalId(match_external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.start(actor_id="system-1")
    match.score_summary = ScoreSummary(
        home_score=80,
        away_score=77,
        periods=(PeriodScore(period=1, home=40, away=38), PeriodScore(period=2, home=40, away=39)),
    )
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
    match_repo.save(match)
    return match

def test_a_c_valid_command_without_finalized_at_uses_issued_at():
    # Test A and C
    match_repo = InMemoryMatchRepository()
    setup_match(match_repo)
    
    issued_at_time = datetime(2026, 8, 8, 12, 0, 0)
    command = FinalizeMatchCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=issued_at_time),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "match_external_id": "2513600",
            "validation_context": {"strict": True}
        },
    )
    
    handler = FinalizeMatchHandler(match_repo)
    events = handler.handle(command)
    
    saved_match = match_repo.get_by_external_id(ExternalId("2513600"))
    assert saved_match.status.value == "FINALIZED"
    
    # Test C: Verify that finalized_at in the Domain Event comes from issued_at
    match_finalized_event = next(e for e in events if e.__class__.__name__ == "MatchFinalized")
    assert match_finalized_event.payload["finalized_at"] == issued_at_time.isoformat()

@patch.object(Match, 'validate_finalization')
def test_b_validation_context_strict_reaches_domain(mock_validate):
    # Test B
    match_repo = InMemoryMatchRepository()
    setup_match(match_repo)
    
    command = FinalizeMatchCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "match_external_id": "2513600",
            "validation_context": {"strict": True}
        },
    )
    
    handler = FinalizeMatchHandler(match_repo)
    handler.handle(command)
    
    # Assert that Match.validate_finalization was called with strict=True
    mock_validate.assert_called_once_with(strict=True)

def test_d_invalid_command_does_not_falsely_generate_success_event():
    # Test D
    match_repo = InMemoryMatchRepository()
    match = setup_match(match_repo)
    
    # Invalidate the match to force a domain validation error (e.g. missing stats)
    match.home_team_stats = None
    match_repo.save(match)
    
    command = FinalizeMatchCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "match_external_id": "2513600",
            "validation_context": {"strict": True}
        },
    )
    
    handler = FinalizeMatchHandler(match_repo)
    events = handler.handle(command)
    
    event_names = [e.__class__.__name__ for e in events]
    assert "MatchValidationStarted" in event_names
    assert "ValidationFailed" in event_names
    assert "MatchValidated" not in event_names
    assert "MatchFinalized" not in event_names
    
    saved_match = match_repo.get_by_external_id(ExternalId("2513600"))
    assert saved_match.status.value != "FINALIZED"
