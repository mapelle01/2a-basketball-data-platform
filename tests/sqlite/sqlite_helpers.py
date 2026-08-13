"""Shared builders and wiring for FASE 9 SQLite integration tests.

`run` is the canonical application wiring: ONE COMMAND -> ONE TRANSACTION ->
aggregate changes + pending events (+ idempotency) -> COMMIT, or full ROLLBACK.
"""

from datetime import datetime
from uuid import uuid4

from feb_score.domain.competition.model import Competition
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    MatchId,
    MatchStatus,
    PeriodScore,
    PlayerId,
    ScoreSummary,
    SeasonCode,
    TeamId,
)


def cmd(payload, role="system", command_id=None):
    return dict(
        command_id=command_id or str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="actor-1", role=role),
        payload=payload,
    )


def run(db, handler, command):
    """Execute a command inside a single transaction, persisting its events atomically."""
    with db.unit_of_work() as uow:
        result = handler.handle(command)
        events = result if isinstance(result, list) else [result]
        uow.append_events(events)
    return result


def scheduled_match() -> Match:
    return Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def ready_to_finalize() -> Match:
    match = scheduled_match()
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
        PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=22, rebounds=9, assists=5, turnovers=2),
    )
    return match


def finalized_match() -> Match:
    match = ready_to_finalize()
    match.finalize(finalized_at=datetime(2026, 2, 1, 20, 0), actor_id="admin-1")
    match.clear_events()
    return match


def make_player() -> Player:
    return Player(external_id=ExternalId("pl-987"), player_id=PlayerId(str(uuid4())), name="Juan")


def make_team() -> Team:
    return Team(external_id=ExternalId("team-123"), team_id=TeamId(str(uuid4())), name="Club")


def make_competition() -> Competition:
    return Competition(external_id=ExternalId("feb-comp"), competition_id=CompetitionId(str(uuid4())), name="League")


def proposal(proposal_id=None, changes=None) -> CorrectionProposal:
    return CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id or str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=changes or [{"op": "update_score", "home_score": 80, "away_score": 77}],
    )


def create_match_command():
    return {
        "external_id": "2513600", "competition_id": "feb-comp", "season_code": "2025-2026",
        "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }


def finalize_command():
    return {"match_external_id": "2513600", "validation_context": {"strict": True}}


def register_command():
    return {
        "player_external_id": "pl-987", "team_external_id": "team-123", "season_code": "2025-2026",
        "dorsal": "12", "registered_from": "2025-08-01T00:00:00Z",
    }