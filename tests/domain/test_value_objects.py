from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.value_objects import (
    Actor,
    CommandMeta,
    CompetitionId,
    CorrectionProposalId,
    EventMeta,
    ExternalId,
    MatchId,
    MatchStatus,
    PeriodScore,
    PlayerId,
    PublicationId,
    RatingValue,
    RatingVersion,
    SeasonCode,
    ScoreSummary,
    SnapshotId,
    Source,
    TeamId,
)


def test_match_id_requires_uuid():
    valid_id = MatchId(str(uuid4()))
    assert str(valid_id) == valid_id.value

    with pytest.raises(ValueError):
        MatchId("invalid-uuid")


def test_player_and_publication_ids_require_uuid():
    assert str(PublicationId(str(uuid4())))

    with pytest.raises(ValueError):
        PublicationId("not-a-uuid")


def test_snapshot_id_requires_uuid():
    assert str(SnapshotId(str(uuid4())))
    with pytest.raises(ValueError):
        SnapshotId("bad-snapshot")


def test_season_code_validation():
    assert str(SeasonCode("2025-2026")) == "2025-2026"
    assert str(SeasonCode("2025-26")) == "2025-26"
    with pytest.raises(ValueError):
        SeasonCode("25-26")
    with pytest.raises(ValueError):
        SeasonCode("")


def test_external_id_must_not_be_empty():
    with pytest.raises(ValueError):
        ExternalId("")


def test_match_status_valid_and_invalid():
    assert str(MatchStatus("SCHEDULED")) == "SCHEDULED"
    assert str(MatchStatus("FINALIZED")) == "FINALIZED"
    with pytest.raises(ValueError):
        MatchStatus("UNKNOWN")


def test_actor_validation():
    actor = Actor(id="admin-1", role="admin")
    assert actor.id == "admin-1"

    with pytest.raises(ValueError):
        Actor(id="user-1", role="invalid-role")

    with pytest.raises(ValueError):
        Actor(id="", role="admin")


def test_command_event_meta_validation():
    assert CommandMeta(version="1.0", issued_at=datetime.utcnow()).version == "1.0"
    assert EventMeta(version="1.0", produced_at=datetime.utcnow()).version == "1.0"

    with pytest.raises(ValueError):
        CommandMeta(version="2.0", issued_at=datetime.utcnow())

    with pytest.raises(ValueError):
        EventMeta(version="2.0", produced_at=datetime.utcnow())


def test_competition_id_must_not_be_empty():
    with pytest.raises(ValueError):
        CompetitionId("")


def test_team_and_player_ids_require_uuid():
    assert str(TeamId(str(uuid4())))
    assert str(PlayerId(str(uuid4())))

    with pytest.raises(ValueError):
        TeamId("bad-team-id")

    with pytest.raises(ValueError):
        PlayerId("bad-player-id")


def test_correction_proposal_id_requires_uuid():
    assert str(CorrectionProposalId(str(uuid4())))
    with pytest.raises(ValueError):
        CorrectionProposalId("bad-proposal-id")


def test_source_origin_validation():
    actor = Actor(id="system-1", role="system")
    assert Source(origin="system", actor=actor).origin == "system"

    with pytest.raises(ValueError):
        Source(origin="external-api", actor=actor)


def test_rating_types():
    assert str(RatingVersion("v1.0")) == "v1.0"
    with pytest.raises(ValueError):
        RatingVersion("")

    assert RatingValue(10.5).value == 10.5
    with pytest.raises(ValueError):
        RatingValue(-1.0)


def test_period_score_validation():
    period = PeriodScore(period=1, home=20, away=18)
    assert period.period == 1
    with pytest.raises(ValueError):
        PeriodScore(period=0, home=10, away=8)
    with pytest.raises(ValueError):
        PeriodScore(period=1, home=-1, away=10)


def test_score_summary_periods_consistency():
    summary = ScoreSummary(
        home_score=60,
        away_score=55,
        periods=(PeriodScore(period=1, home=30, away=25), PeriodScore(period=2, home=30, away=30)),
    )
    assert summary.home_score == 60
    assert summary.away_score == 55
    assert summary.total_points == 115

    with pytest.raises(ValueError):
        ScoreSummary(home_score=60, away_score=55, periods=(PeriodScore(period=1, home=20, away=25),))

    with pytest.raises(ValueError):
        ScoreSummary(home_score=-1, away_score=10)
