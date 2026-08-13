from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.errors import InvalidStandingSnapshot
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.standings.model import StandingSnapshot
from feb_score.domain.value_objects import CompetitionId, ExternalId, MatchId, SeasonCode


def make_finalized_match(external_id: str, home_score: int, away_score: int) -> Match:
    match = Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=1,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.score_summary = None
    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=home_score,
        points_against=away_score,
        field_goals_made=25,
        field_goals_attempted=50,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=10,
        free_throws_attempted=12,
        turnovers=8,
        rebounds=32,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=away_score,
        points_against=home_score,
        field_goals_made=24,
        field_goals_attempted=52,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=11,
        free_throws_attempted=13,
        turnovers=9,
        rebounds=30,
    )
    match.player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=20,
            rebounds=8,
            assists=5,
        ),
    )
    from feb_score.domain.value_objects import PeriodScore, ScoreSummary

    match.score_summary = ScoreSummary(
        home_score=home_score,
        away_score=away_score,
        periods=(PeriodScore(period=1, home=home_score // 2, away=away_score // 2), PeriodScore(period=2, home=home_score - home_score // 2, away=away_score - away_score // 2)),
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")
    return match


def test_standing_snapshot_from_matches():
    match1 = make_finalized_match("match-1", home_score=80, away_score=75)
    match2 = make_finalized_match("match-2", home_score=72, away_score=78)

    snapshot = StandingSnapshot.from_matches(
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        matches=[match1, match2],
        rules_version="rules-v1",
        generated_at=datetime.utcnow(),
    )

    assert snapshot.matches_count == 2
    assert all(entry.played == 2 for entry in snapshot.entries)
    assert snapshot.entries[0].points >= snapshot.entries[-1].points


def test_standing_snapshot_skips_non_finalized_and_wrong_season_matches():
    finalized = make_finalized_match("match-4", home_score=70, away_score=68)
    scheduled = make_finalized_match("match-5", home_score=60, away_score=58)
    scheduled.status = type(scheduled.status)("SCHEDULED")

    wrong_season = make_finalized_match("match-6", home_score=55, away_score=50)
    wrong_season.season_code = SeasonCode("2024-2025")

    snapshot = StandingSnapshot.from_matches(
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        matches=[scheduled, wrong_season, finalized],
        rules_version="rules-v1",
        generated_at=datetime.utcnow(),
    )

    assert snapshot.matches_count == 1


def test_standing_snapshot_requires_finalized_matches():
    match = make_finalized_match("match-3", home_score=63, away_score=65)
    match.status = type(match.status)("SCHEDULED")
    with pytest.raises(InvalidStandingSnapshot):
        StandingSnapshot.from_matches(
            competition_id=CompetitionId("feb-competition"),
            season_code=SeasonCode("2025-2026"),
            matches=[match],
            rules_version="rules-v1",
            generated_at=datetime.utcnow(),
        )
