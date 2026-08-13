from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import ApproveCorrectionCommand, ProposeCorrectionCommand
from feb_score.application.repositories.in_memory import InMemoryCorrectionRepository, InMemoryMatchRepository
from feb_score.application.use_cases.handlers import ApproveCorrectionHandler, ProposeCorrectionHandler
from feb_score.domain.correction.model import CorrectionProposal
from feb_score.domain.errors import InvalidCorrection, UnauthorizedCorrection
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import TeamStats, PlayerStats
from feb_score.domain.value_objects import Actor, CommandMeta, CompetitionId, CorrectionProposalId, ExternalId, MatchId, PeriodScore, ScoreSummary, SeasonCode


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
        team_external_id="team-home",
        points_for=78,
        points_against=75,
        field_goals_made=28,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=22,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=11,
        rebounds=35,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=75,
        points_against=78,
        field_goals_made=27,
        field_goals_attempted=61,
        three_points_made=7,
        three_points_attempted=20,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=33,
    )
    match.player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=25,
            rebounds=8,
            assists=4,
        ),
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")
    return match


def test_propose_and_approve_correction():
    correction_repo = InMemoryCorrectionRepository()
    match_repo = InMemoryMatchRepository()
    match = make_finalized_match()
    match_repo.save(match)

    propose = ProposeCorrectionHandler(correction_repo)
    command = ProposeCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="editor-1", role="editor"),
        payload={
            "match_external_id": "2513600",
            "proposed_by": {"id": "editor-1", "role": "editor"},
            "reason": "Official score correction",
            "changes": [{"op": "update_score", "home_score": 78, "away_score": 75}],
        },
    )
    event = propose.handle(command)
    assert event.payload["proposal_id"] == command.command_id
    assert correction_repo.get_by_id(command.command_id) is not None

    approve = ApproveCorrectionHandler(correction_repo, match_repo)
    approve_command = ApproveCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "proposal_id": command.command_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": datetime.utcnow().isoformat(),
        },
    )
    events = approve.handle(approve_command)
    assert any(e.__class__.__name__ == "CorrectionApproved" for e in events)
    assert any(e.__class__.__name__ == "MatchUpdatedByCorrection" for e in events)


def test_approve_correction_is_atomic_when_match_application_fails():
    correction_repo = InMemoryCorrectionRepository()
    match_repo = InMemoryMatchRepository()
    match = make_finalized_match()
    match.clear_events()
    match_repo.save(match)

    proposal_id = str(uuid4())
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Official score correction",
        changes=[{"op": "update_score", "home_score": 79, "away_score": 75}],
    )
    correction_repo.save(proposal)

    approve = ApproveCorrectionHandler(correction_repo, match_repo)
    approve_command = ApproveCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "proposal_id": proposal_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": datetime.utcnow().isoformat(),
        },
    )

    with pytest.raises(InvalidCorrection):
        approve.handle(approve_command)

    stored_proposal = correction_repo.get_by_id(proposal_id)
    stored_match = match_repo.get_by_external_id(ExternalId("2513600"))

    assert stored_proposal.status == "PROPOSED"
    assert stored_proposal.approved_by is None
    assert stored_proposal.approved_at is None
    assert stored_proposal.previous_version is None
    assert stored_proposal.new_version is None

    assert stored_match.score_summary.home_score == 78
    assert stored_match.score_summary.away_score == 75
    assert [(p.period, p.home, p.away) for p in stored_match.score_summary.periods] == [(1, 40, 35), (2, 38, 40)]
    assert stored_match.version == 2
    assert stored_match.correction_history == []
    assert stored_match.collect_events() == []


def test_approve_correction_success_updates_match_then_approves_and_emits_events():
    correction_repo = InMemoryCorrectionRepository()
    match_repo = InMemoryMatchRepository()
    match = make_finalized_match()
    match.clear_events()
    match_repo.save(match)

    proposal_id = str(uuid4())
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 78, "away_score": 75}],
    )
    correction_repo.save(proposal)

    approve = ApproveCorrectionHandler(correction_repo, match_repo)
    approve_command = ApproveCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "proposal_id": proposal_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": datetime.utcnow().isoformat(),
        },
    )

    events = approve.handle(approve_command)
    event_names = [event.__class__.__name__ for event in events]
    stored_proposal = correction_repo.get_by_id(proposal_id)
    stored_match = match_repo.get_by_external_id(ExternalId("2513600"))

    assert stored_match.version == 3
    assert len(stored_match.correction_history) == 1
    assert stored_proposal.status == "APPROVED"
    assert stored_proposal.approved_by.id == "admin-1"
    assert stored_proposal.previous_version == "2"
    assert stored_proposal.new_version == "3"
    assert event_names == ["MatchUpdatedByCorrection", "CorrectionApproved"]
    assert stored_match.collect_events() == []


def test_approve_correction_twice_rejects_second_attempt_without_touching_match():
    correction_repo = InMemoryCorrectionRepository()
    match_repo = InMemoryMatchRepository()
    match = make_finalized_match()
    match.clear_events()
    match_repo.save(match)

    proposal_id = str(uuid4())
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(proposal_id),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Official score confirmation",
        changes=[{"op": "update_score", "home_score": 78, "away_score": 75}],
    )
    correction_repo.save(proposal)

    approve = ApproveCorrectionHandler(correction_repo, match_repo)
    command = ApproveCorrectionCommand(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="admin-1", role="admin"),
        payload={
            "proposal_id": proposal_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": datetime.utcnow().isoformat(),
        },
    )

    approve.handle(command)
    stored_match = match_repo.get_by_external_id(ExternalId("2513600"))
    stored_match.clear_events()

    with pytest.raises(InvalidCorrection):
        approve.handle(command)

    assert correction_repo.get_by_id(proposal_id).status == "APPROVED"
    assert stored_match.version == 3
    assert len(stored_match.correction_history) == 1
    assert stored_match.collect_events() == []


def test_reject_correction():
    correction_repo = InMemoryCorrectionRepository()
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Manual correction needed",
        changes=[{"op": "update_score", "home_score": 79, "away_score": 75}],
    )
    correction_repo.save(proposal)

    with pytest.raises(UnauthorizedCorrection):
        proposal.reject(approver=Actor(id="user-1", role="editor"), rejected_at=datetime.utcnow(), reason="Not allowed")


def test_approval_requires_admin_role():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Manual correction needed",
        changes=[{"op": "update_score", "home_score": 79, "away_score": 75}],
    )
    with pytest.raises(UnauthorizedCorrection):
        proposal.approve(
            approver=Actor(id="editor-2", role="editor"),
            approved_at=datetime.utcnow(),
            previous_version="v1",
            new_version="v2",
        )


def test_approving_already_approved_proposal_is_invalid():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Manual correction",
        changes=[{"op": "update_score", "home_score": 79, "away_score": 75}],
    )
    proposal.approve(
        approver=Actor(id="admin-1", role="admin"),
        approved_at=datetime.utcnow(),
        previous_version="1",
        new_version="2",
    )

    with pytest.raises(InvalidCorrection):
        proposal.approve(
            approver=Actor(id="admin-1", role="admin"),
            approved_at=datetime.utcnow(),
            previous_version="2",
            new_version="3",
        )


def test_rejecting_already_rejected_proposal_is_invalid():
    proposal = CorrectionProposal(
        proposal_id=CorrectionProposalId(str(uuid4())),
        match_external_id=ExternalId("2513600"),
        proposed_by=Actor(id="editor-1", role="editor"),
        proposed_at=datetime.utcnow(),
        reason="Manual correction",
        changes=[{"op": "update_score", "home_score": 79, "away_score": 75}],
    )
    proposal.reject(approver=Actor(id="admin-1", role="admin"), rejected_at=datetime.utcnow(), reason="Not allowed")

    with pytest.raises(InvalidCorrection):
        proposal.reject(approver=Actor(id="admin-1", role="admin"), rejected_at=datetime.utcnow(), reason="Second reject")
