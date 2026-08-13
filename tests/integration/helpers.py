"""Shared builders for FASE 7 integration tests."""

from datetime import datetime
from uuid import uuid4

from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    MatchId,
    PeriodScore,
    PlayerId,
    ScoreSummary,
    SeasonCode,
    TeamId,
)


def scheduled_match(external_id: str = "2513600", competition: str = "unknown") -> Match:
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId(competition),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def finalized_match(external_id: str = "2513600", competition: str = "unknown") -> Match:
    match = scheduled_match(external_id, competition)
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
    match.player_stats = (
        PlayerStats(
            player_external_id="pl-1", team_external_id="team-home",
            points=22, rebounds=9, assists=5, turnovers=2,
        ),
    )
    match.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    match.clear_events()
    return match


def make_player(external_id: str = "pl-987") -> Player:
    return Player(external_id=ExternalId(external_id), player_id=PlayerId(str(uuid4())), name="Juan")


def make_team(external_id: str = "team-123") -> Team:
    return Team(external_id=ExternalId(external_id), team_id=TeamId(str(uuid4())), name="Club")


def proposed_correction(
    proposal_id: str,
    match_external_id: str = "2513600",
    changes=None,
) -> CorrectionProposal:
    return CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id),
        match_external_id=ExternalId(match_external_id),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=changes or [{"op": "update_score", "home_score": 80, "away_score": 77}],
    )