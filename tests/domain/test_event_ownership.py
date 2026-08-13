"""FASE 6 — Domain Event ownership & emission-timing tests.

Verifies that events are:
- owned by the aggregate/service that owns the state change
- emitted only after the domain operation succeeds
- not duplicated
"""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.repositories.in_memory import InMemoryCorrectionRepository, InMemoryMatchRepository
from feb_score.application.commands.commands import ApproveCorrectionCommand
from feb_score.application.use_cases.handlers import ApproveCorrectionHandler
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.errors import InvalidCorrection, InvalidLeaderboardCategory, MissingMatchData
from feb_score.domain.leaderboard.model import Leaderboard
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    MatchId,
    PeriodScore,
    ScoreSummary,
    SeasonCode,
)


def make_finalized_match() -> Match:
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.score_summary = ScoreSummary(
        home_score=78,
        away_score=75,
        periods=(PeriodScore(period=1, home=40, away=35), PeriodScore(period=2, home=38, away=40)),
    )
    match.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=78, points_against=75,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=22, free_throws_made=14, free_throws_attempted=18,
        turnovers=11, rebounds=35,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=75, points_against=78,
        field_goals_made=27, field_goals_attempted=61, three_points_made=7,
        three_points_attempted=20, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=33,
    )
    match.player_stats = (
        PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=25, rebounds=8, assists=4),
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")
    match.clear_events()
    return match


def test_match_finalized_emitted_once_after_successful_finalize():
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.score_summary = ScoreSummary(home_score=78, away_score=75, periods=())
    match.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=78, points_against=75,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=22, free_throws_made=14, free_throws_attempted=18,
        turnovers=11, rebounds=35,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=75, points_against=78,
        field_goals_made=27, field_goals_attempted=61, three_points_made=7,
        three_points_attempted=20, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=33,
    )
    match.finalize(finalized_at=datetime(2026, 2, 2, 20, 0), actor_id="admin-1")
    events = match.collect_events()
    assert [e.__class__.__name__ for e in events] == ["MatchFinalized"]
    assert events[0].payload["external_id"] == "2513600"


def test_match_finalize_failure_emits_no_events():
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    with pytest.raises(MissingMatchData):
        match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    assert match.collect_events() == []
    assert match.status.value == "SCHEDULED"


def test_match_updated_by_correction_not_emitted_on_unsupported_op():
    match = make_finalized_match()
    version_before = match.version

    with pytest.raises(InvalidCorrection):
        match.apply_correction(
            correction_id=str(uuid4()),
            changes=[{"op": "add_event", "event": {"minute": 34, "type": "technical"}}],
            approved_at=datetime.utcnow(),
            approver_id="admin-1",
            reason="Unsupported",
        )

    assert match.collect_events() == []
    assert match.version == version_before
    assert match.correction_history == []


def test_correction_proposal_approve_emits_correction_approved_from_aggregate():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 78, "away_score": 75}],
    )
    proposal.approve(
        approver=Actor(id="admin-1", role="admin"),
        approved_at=datetime(2026, 2, 2, 12, 0),
        previous_version="2",
        new_version="3",
    )

    events = proposal.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "CorrectionApproved"
    assert events[0].payload["proposal_id"] == str(proposal.proposal_id)
    assert events[0].payload["new_version"] == "3"


def test_correction_proposal_reject_emits_correction_rejected_from_aggregate():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 78, "away_score": 75}],
    )
    proposal.reject(
        approver=Actor(id="admin-1", role="admin"),
        rejected_at=datetime(2026, 2, 2, 13, 0),
        reason="Incorrect proposal",
    )

    events = proposal.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "CorrectionRejected"
    assert events[0].payload["reason"] == "Incorrect proposal"


def test_approve_correction_handler_emits_no_duplicate_events():
    correction_repo = InMemoryCorrectionRepository()
    match_repo = InMemoryMatchRepository()
    match = make_finalized_match()
    match_repo.save(match)

    proposal_id = str(uuid4())
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime(2026, 2, 2, 10, 0),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 78, "away_score": 75}],
    )
    correction_repo.save(proposal)

    handler = ApproveCorrectionHandler(correction_repo, match_repo)
    events = handler.handle(
        ApproveCorrectionCommand(
            command_id=str(uuid4()),
            meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
            actor=Actor(id="admin-1", role="admin"),
            payload={
                "proposal_id": proposal_id,
                "approved_by": {"id": "admin-1", "role": "admin"},
                "approved_at": "2026-02-02T12:00:00Z",
            },
        )
    )

    event_names = [e.__class__.__name__ for e in events]
    event_ids = [e.event_id for e in events]
    assert event_names == ["MatchUpdatedByCorrection", "CorrectionApproved"]
    assert len(event_ids) == len(set(event_ids))


def test_leaderboard_invalid_category_raises_before_any_event():
    with pytest.raises(InvalidLeaderboardCategory):
        Leaderboard.from_matches(
            season_code=SeasonCode("2025-2026"),
            category="not_a_real_category",
            matches=[],
            min_games=0,
            top_n=10,
            generated_at=datetime.utcnow(),
        )