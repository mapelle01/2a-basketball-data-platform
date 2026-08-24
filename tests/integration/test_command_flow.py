"""FASE 7 — End-to-end command flow integration tests.

Demonstrates COMMAND → VALIDATION → HANDLER → DOMAIN → PERSISTENCE → EVENTS
for valid and invalid operations, proving no partial state on failure and
no events emitted unless the operation succeeded.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.application.commands.commands import (
    ApproveCorrectionCommand,
    BackfillSeasonCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    CreatePublicationCommand,
    FinalizeMatchCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
)
from feb_score.application.repositories.in_memory import (
    InMemoryCompetitionRepository,
    InMemoryCorrectionRepository,
    InMemoryLeaderboardRepository,
    InMemoryMatchRepository,
    InMemoryPlayerRepository,
    InMemoryPublicationRepository,
    InMemoryRatingRepository,
    InMemoryStandingRepository,
    InMemoryTeamRepository,
)
from feb_score.application.use_cases.handlers import (
    ApproveCorrectionHandler,
    BackfillSeasonHandler,
    ComputePlayerRatingHandler,
    CreateOrUpdateMatchHandler,
    CreatePublicationHandler,
    FinalizeMatchHandler,
    GenerateLeaderboardHandler,
    GenerateStandingSnapshotHandler,
    ProposeCorrectionHandler,
    RegisterPlayerToSquadHandler,
)
from feb_score.application.validation import ContractValidationError
from feb_score.domain.errors import (
    EntityNotFound,
    InvalidCorrection,
    InvalidLeaderboardCategory,
    InvalidPlayerRegistration,
    InvalidRatingCalculation,
    InvalidStandingSnapshot,
)
from feb_score.domain.statistics.model import TeamStats
from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    ExternalId,
    PeriodScore,
    ScoreSummary,
    SeasonCode,
)

from helpers import finalized_match, make_player, make_team, proposed_correction, scheduled_match


def cmd(payload, role="system"):
    return dict(
        command_id=str(uuid4()),
        meta=CommandMeta(version="1.0", issued_at=datetime.utcnow()),
        actor=Actor(id="actor-1", role=role),
        payload=payload,
    )


# --- CreateOrUpdateMatch ---
def test_create_or_update_match_valid_persists_state_and_emits_event():
    repo = InMemoryMatchRepository()
    handler = CreateOrUpdateMatchHandler(repo)
    events = handler.handle(
        CreateOrUpdateMatchCommand(**cmd({
            "external_id": "2513600", "competition_id": "feb-competition", "season_code": "2025-2026",
            "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
            "home_team": {"external_id": "team-home", "name": "Home"},
            "away_team": {"external_id": "team-away", "name": "Away"},
            "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
        }))
    )
    match = repo.get_by_external_id(ExternalId("2513600"))
    assert match is not None and match.status.value == "SCHEDULED"
    assert [e.__class__.__name__ for e in events] == ["MatchUpserted"]


def test_create_or_update_match_invalid_payload_changes_nothing():
    repo = InMemoryMatchRepository()
    handler = CreateOrUpdateMatchHandler(repo)
    with pytest.raises(ContractValidationError):
        handler.handle(
            CreateOrUpdateMatchCommand(**cmd({
                "external_id": "2513600", "season_code": "2025-2026",
                "home_team": {"external_id": "t1", "name": "A"},
                "away_team": {"external_id": "t2", "name": "B"},
                "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z"},
            }))
        )
    assert repo.get_by_external_id(ExternalId("2513600")) is None


def test_create_or_update_match_domain_invariant_violation_changes_nothing():
    repo = InMemoryMatchRepository()
    handler = CreateOrUpdateMatchHandler(repo)
    with pytest.raises(ValueError):
        handler.handle(
            CreateOrUpdateMatchCommand(**cmd({
                "external_id": "2513600", "season_code": "2025-2026",
                "round_number": 5, "scheduled_at": "2026-02-01T18:30:00Z",
                "home_team": {"external_id": "same", "name": "A"},
                "away_team": {"external_id": "same", "name": "B"},
                "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z"},
            }))
        )
    assert repo.get_by_external_id(ExternalId("2513600")) is None


# --- FinalizeMatch ---
def _ready_to_finalize():
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
    return match


def test_finalize_match_valid_persists_finalized_and_emits_success_events():
    repo = InMemoryMatchRepository()
    repo.save(_ready_to_finalize())

    events = FinalizeMatchHandler(repo).handle(
        FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))
    )
    names = [e.__class__.__name__ for e in events]
    assert names == ["MatchValidationStarted", "MatchValidated", "MatchFinalized"]
    assert repo.get_by_external_id(ExternalId("2513600")).status.value == "FINALIZED"


def test_finalize_match_invalid_domain_state_persists_nothing_new():
    repo = InMemoryMatchRepository()
    repo.save(_ready_to_finalize())

    events = FinalizeMatchHandler(repo).handle(
        FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))
    )
    names = [e.__class__.__name__ for e in events]
    assert names == ["MatchValidationStarted", "MatchValidated", "MatchFinalized"]
    assert repo.get_by_external_id(ExternalId("2513600")).status.value == "FINALIZED"


def test_finalize_match_missing_score_persists_no_new_state():
    repo = InMemoryMatchRepository()
    match = _ready_to_finalize()
    match.score_summary = None  # break the domain invariant
    repo.save(match)

    events = FinalizeMatchHandler(repo).handle(
        FinalizeMatchCommand(**cmd({"match_external_id": "2513600", "validation_context": {"strict": True}}, role="admin"))
    )
    names = [e.__class__.__name__ for e in events]
    assert names == ["MatchValidationStarted", "ValidationFailed"]
    assert "MatchFinalized" not in names
    assert repo.get_by_external_id(ExternalId("2513600")).status.value == "SCHEDULED"


def test_finalize_match_with_score_in_command_finalizes_provisional_match():
    """A provisional match (create + upsert stats) has team stats but NO score;
    the finalize command carries the score so it can reach FINALIZED. Regression
    guard for the backfill: without a score in the command, finalize is a no-op."""
    repo = InMemoryMatchRepository()
    match = _ready_to_finalize()
    match.score_summary = None  # provisional: score not recorded by create/upsert
    repo.save(match)

    events = FinalizeMatchHandler(repo).handle(
        FinalizeMatchCommand(**cmd({
            "match_external_id": "2513600",
            "score_summary": {"home_score": 80, "away_score": 77,
                              "periods": [{"period": 1, "home": 40, "away": 38},
                                          {"period": 2, "home": 40, "away": 39}]},
            "validation_context": {"strict": False},
        }, role="system"))
    )
    assert "MatchFinalized" in [e.__class__.__name__ for e in events]
    finalized = repo.get_by_external_id(ExternalId("2513600"))
    assert finalized.status.value == "FINALIZED"
    assert finalized.score_summary.home_score == 80
    assert len(finalized.score_summary.periods) == 2


# --- ProposeCorrection / ApproveCorrection ---
def test_approve_correction_valid_updates_both_aggregates_and_emits_events():
    crepo = InMemoryCorrectionRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())

    proposal_id = str(uuid4())
    crepo.save(proposed_correction(proposal_id))

    events = ApproveCorrectionHandler(crepo, mrepo).handle(
        ApproveCorrectionCommand(**cmd({
            "proposal_id": proposal_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": "2026-02-02T12:00:00Z",
        }, role="admin"))
    )
    assert crepo.get_by_id(proposal_id).status == "APPROVED"
    assert mrepo.get_by_external_id(ExternalId("2513600")).version == 3
    assert [e.__class__.__name__ for e in events] == ["MatchUpdatedByCorrection", "CorrectionApproved"]


def test_approve_correction_invalid_op_changes_no_state_and_emits_no_events():
    crepo = InMemoryCorrectionRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())

    proposal_id = str(uuid4())
    crepo.save(proposed_correction(proposal_id, changes=[{"op": "add_event", "event": {"minute": 34}}]))

    with pytest.raises(InvalidCorrection):
        ApproveCorrectionHandler(crepo, mrepo).handle(
            ApproveCorrectionCommand(**cmd({
                "proposal_id": proposal_id,
                "approved_by": {"id": "admin-1", "role": "admin"},
                "approved_at": "2026-02-02T12:00:00Z",
            }, role="admin"))
        )
    assert crepo.get_by_id(proposal_id).status == "PROPOSED"
    assert mrepo.get_by_external_id(ExternalId("2513600")).version == 2


# --- RegisterPlayerToSquad ---
def test_register_player_valid_updates_both_aggregates_and_emits_event():
    prepo = InMemoryPlayerRepository()
    trepo = InMemoryTeamRepository()
    prepo.save(make_player())
    trepo.save(make_team())

    event = RegisterPlayerToSquadHandler(prepo, trepo).handle(
        RegisterPlayerToSquadCommand(**cmd({
            "player_external_id": "pl-987", "team_external_id": "team-123", "season_code": "2025-2026",
            "dorsal": "12", "registered_from": "2025-08-01T00:00:00Z",
        }, role="admin"))
    )
    assert prepo.get_by_external_id(ExternalId("pl-987")).registrations[0].dorsal == 12
    assert trepo.get_by_external_id(ExternalId("team-123")).registrations[0].dorsal == 12
    assert event.__class__.__name__ == "PlayerRegistered"


def test_register_player_duplicate_changes_no_state():
    prepo = InMemoryPlayerRepository()
    trepo = InMemoryTeamRepository()
    prepo.save(make_player())
    trepo.save(make_team())
    handler = RegisterPlayerToSquadHandler(prepo, trepo)
    payload = {
        "player_external_id": "pl-987", "team_external_id": "team-123", "season_code": "2025-2026",
        "dorsal": "12", "registered_from": "2025-08-01T00:00:00Z",
    }
    handler.handle(RegisterPlayerToSquadCommand(**cmd(payload, role="admin")))

    with pytest.raises(InvalidPlayerRegistration):
        handler.handle(RegisterPlayerToSquadCommand(**cmd(payload, role="admin")))

    assert len(prepo.get_by_external_id(ExternalId("pl-987")).registrations) == 1
    assert len(trepo.get_by_external_id(ExternalId("team-123")).registrations) == 1


# --- ComputePlayerRating ---
def test_compute_rating_valid_persists_rating_and_emits_events():
    mrepo = InMemoryMatchRepository()
    rrepo = InMemoryRatingRepository()
    mrepo.save(finalized_match())

    events = ComputePlayerRatingHandler(mrepo, rrepo).handle(
        ComputePlayerRatingCommand(**cmd({
            "player_external_id": "pl-1", "season_code": "2025-2026", "rating_version": "v1.0",
        }))
    )
    assert len(rrepo._ratings) == 1
    assert any(e.__class__.__name__ == "PlayerRatingComputed" for e in events)


def test_compute_rating_no_data_persists_nothing():
    mrepo = InMemoryMatchRepository()
    rrepo = InMemoryRatingRepository()
    with pytest.raises(InvalidRatingCalculation):
        ComputePlayerRatingHandler(mrepo, rrepo).handle(
            ComputePlayerRatingCommand(**cmd({
                "player_external_id": "nobody", "season_code": "2025-2026", "rating_version": "v1.0",
            }))
        )
    assert rrepo._ratings == []


# --- GenerateStandingSnapshot ---
def test_generate_standing_valid_persists_snapshot_and_emits_event():
    srepo = InMemoryStandingRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())

    event = GenerateStandingSnapshotHandler(srepo, mrepo).handle(
        GenerateStandingSnapshotCommand(**cmd({
            "competition_id": "unknown", "season_code": "2025-2026",
            "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
        }))
    )
    assert len(srepo._standings) == 1
    assert event.__class__.__name__ == "StandingSnapshotGenerated"
    assert event.payload["matches_included_count"] == 1


def test_generate_standing_no_matches_persists_nothing():
    srepo = InMemoryStandingRepository()
    mrepo = InMemoryMatchRepository()
    with pytest.raises(InvalidStandingSnapshot):
        GenerateStandingSnapshotHandler(srepo, mrepo).handle(
            GenerateStandingSnapshotCommand(**cmd({
                "competition_id": "unknown", "season_code": "2025-2026",
                "as_of": "2026-02-01T23:59:59Z", "rules_version": "rules-v1",
            }))
        )
    assert srepo._standings == []


# --- GenerateLeaderboard ---
def test_generate_leaderboard_valid_persists_leaderboard_and_emits_event():
    lrepo = InMemoryLeaderboardRepository()
    mrepo = InMemoryMatchRepository()
    mrepo.save(finalized_match())

    event = GenerateLeaderboardHandler(mrepo, lrepo).handle(
        GenerateLeaderboardCommand(**cmd({
            "season_code": "2025-2026", "category": "points_per_game", "min_games": 0, "top_n": 10,
        }))
    )
    assert len(lrepo._leaderboards) == 1
    stored = list(lrepo._leaderboards.values())[0]
    assert stored.category == "points_per_game"
    assert event.payload["leaderboard_id"] == str(stored.leaderboard_id)


def test_generate_leaderboard_invalid_category_persists_nothing():
    lrepo = InMemoryLeaderboardRepository()
    mrepo = InMemoryMatchRepository()
    with pytest.raises(InvalidLeaderboardCategory):
        GenerateLeaderboardHandler(mrepo, lrepo).handle(
            GenerateLeaderboardCommand(**cmd({
                "season_code": "2025-2026", "category": "nope", "min_games": 0, "top_n": 10,
            }))
        )
    assert lrepo._leaderboards == {}


# --- CreatePublication ---
def test_create_publication_valid_persists_and_emits_event():
    prepo = InMemoryPublicationRepository()
    event = CreatePublicationHandler(prepo).handle(
        CreatePublicationCommand(**cmd({
            "template_id": "tpl-1", "payload_refs": {"match_external_id": "2513600"},
            "scheduled_at": "2026-02-02T08:00:00Z",
        }, role="editor"))
    )
    assert len(prepo._publications) == 1
    assert [e.__class__.__name__ for e in event] == ["PublicationCreated"]


# --- BackfillSeason ---
def test_backfill_season_missing_competition_emits_no_events():
    with pytest.raises(EntityNotFound):
        BackfillSeasonHandler(InMemoryCompetitionRepository()).handle(
            BackfillSeasonCommand(**cmd({
                "competition_id": "missing", "season_code": "2025-2026", "from_round": 1, "to_round": 5,
            }, role="admin"))
        )