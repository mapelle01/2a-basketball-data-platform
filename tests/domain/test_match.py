from datetime import datetime
from uuid import uuid4

import pytest
from hypothesis import given, strategies as st

from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import TeamStats, PlayerStats
from feb_score.domain.value_objects import PeriodScore, ScoreSummary
from feb_score.domain.errors import InvalidCorrection, InvalidMatchStateTransition, InvalidScore, MatchAlreadyFinalized, MissingMatchData
from feb_score.domain.value_objects import CompetitionId, ExternalId, MatchId, SeasonCode


def make_match() -> Match:
    return Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-competition"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def test_match_rejects_identical_home_and_away_teams():
    with pytest.raises(ValueError, match="must differ"):
        Match(
            external_id=ExternalId("2513600"),
            match_id=MatchId(str(uuid4())),
            competition_id=CompetitionId("feb-competition"),
            season_code=SeasonCode("2025-2026"),
            round_number=5,
            home_team_id=ExternalId("team-home"),
            away_team_id=ExternalId("team-home"),
            scheduled_at=datetime(2026, 2, 1, 18, 30),
        )


def test_match_rejects_negative_round_number():
    with pytest.raises(ValueError, match="round_number"):
        Match(
            external_id=ExternalId("2513600"),
            match_id=MatchId(str(uuid4())),
            competition_id=CompetitionId("feb-competition"),
            season_code=SeasonCode("2025-2026"),
            round_number=-1,
            home_team_id=ExternalId("team-home"),
            away_team_id=ExternalId("team-away"),
            scheduled_at=datetime(2026, 2, 1, 18, 30),
        )


def test_create_and_update_match():
    match = make_match()
    assert match.status.value == "SCHEDULED"
    assert match.round_number == 5

    match.upsert(round_number=6)
    assert match.round_number == 6


def test_match_state_transitions():
    match = make_match()
    match.start(actor_id="system")
    assert match.status.value == "IN_PLAY"

    with pytest.raises(InvalidMatchStateTransition):
        match.start(actor_id="system")

    match.cancel(actor_id="system")
    assert match.status.value == "CANCELLED"

    with pytest.raises(InvalidMatchStateTransition):
        match.postpone(actor_id="system")


def test_match_can_be_postponed_from_scheduled():
    match = make_match()
    match.postpone(actor_id="admin-1")
    assert match.status.value == "POSTPONED"

    with pytest.raises(InvalidMatchStateTransition):
        match.cancel(actor_id="admin-1")


def test_upsert_triggers_event_recording():
    match = make_match()
    initial_events = list(match.collect_events())
    match.upsert(round_number=7)
    events = match.collect_events()
    assert len(events) == 1
    assert match.round_number == 7
    assert events[0].payload["status"] == "SCHEDULED"


def test_finalize_match_valid():
    match = make_match()
    score = ScoreSummary(
        home_score=80,
        away_score=75,
        periods=(PeriodScore(period=1, home=40, away=35), PeriodScore(period=2, home=40, away=40)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=80,
        points_against=75,
        field_goals_made=30,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=12,
        free_throws_attempted=16,
        turnovers=10,
        rebounds=38,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=75,
        points_against=80,
        field_goals_made=28,
        field_goals_attempted=62,
        three_points_made=6,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=34,
    )
    player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=25,
            rebounds=10,
            assists=5,
        ),
    )

    match.score_summary = score
    match.home_team_stats = home_stats
    match.away_team_stats = away_stats
    match.player_stats = player_stats

    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    assert match.status.value == "FINALIZED"
    assert match.version == 2
    assert match.collect_events()


def test_cannot_finalize_already_finalized_match():
    match = make_match()
    score = ScoreSummary(
        home_score=80,
        away_score=75,
        periods=(PeriodScore(period=1, home=40, away=35), PeriodScore(period=2, home=40, away=40)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=80,
        points_against=75,
        field_goals_made=30,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=12,
        free_throws_attempted=16,
        turnovers=10,
        rebounds=38,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=75,
        points_against=80,
        field_goals_made=28,
        field_goals_attempted=62,
        three_points_made=6,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=34,
    )
    match.score_summary = score
    match.home_team_stats = home_stats
    match.away_team_stats = away_stats
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    with pytest.raises(MatchAlreadyFinalized):
        match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")


def test_finalize_accepts_optional_parameters():
    match = make_match()
    score = ScoreSummary(
        home_score=80,
        away_score=75,
        periods=(PeriodScore(period=1, home=40, away=35), PeriodScore(period=2, home=40, away=40)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=80,
        points_against=75,
        field_goals_made=30,
        field_goals_attempted=60,
        three_points_made=8,
        three_points_attempted=20,
        free_throws_made=12,
        free_throws_attempted=16,
        turnovers=10,
        rebounds=38,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=75,
        points_against=80,
        field_goals_made=28,
        field_goals_attempted=62,
        three_points_made=6,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=18,
        turnovers=12,
        rebounds=34,
    )
    player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=25,
            rebounds=10,
            assists=5,
        ),
    )

    match.finalize(
        score_summary=score,
        home_team_stats=home_stats,
        away_team_stats=away_stats,
        player_stats=player_stats,
        actor_id="admin-1",
    )

    assert match.status.value == "FINALIZED"
    assert match.score_summary.home_score == 80
    assert len(match.player_stats) == 1


def test_finalize_rejects_zero_point_game():
    match = make_match()
    match.score_summary = ScoreSummary(home_score=0, away_score=0)
    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=0,
        points_against=0,
        field_goals_made=0,
        field_goals_attempted=0,
        three_points_made=0,
        three_points_attempted=0,
        free_throws_made=0,
        free_throws_attempted=0,
        turnovers=0,
        rebounds=0,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=0,
        points_against=0,
        field_goals_made=0,
        field_goals_attempted=0,
        three_points_made=0,
        three_points_attempted=0,
        free_throws_made=0,
        free_throws_attempted=0,
        turnovers=0,
        rebounds=0,
    )
    with pytest.raises(InvalidScore, match="result"):
        match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")


def test_prevent_finalize_without_statistics():
    match = make_match()
    with pytest.raises(MissingMatchData):
        match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")


def test_prevent_finalize_from_bad_state():
    match = make_match()
    match.status = match.status = type(match.status)("CANCELLED")
    with pytest.raises(InvalidMatchStateTransition):
        match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")


def test_apply_correction_to_finalized_match():
    match = make_match()
    score = ScoreSummary(
        home_score=70,
        away_score=68,
        periods=(PeriodScore(period=1, home=35, away=34), PeriodScore(period=2, home=35, away=34)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=70,
        points_against=68,
        field_goals_made=25,
        field_goals_attempted=55,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=16,
        turnovers=11,
        rebounds=36,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=68,
        points_against=70,
        field_goals_made=24,
        field_goals_attempted=57,
        three_points_made=6,
        three_points_attempted=17,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=13,
        rebounds=33,
    )
    player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=20,
            rebounds=8,
            assists=4,
        ),
    )
    match.score_summary = score
    match.home_team_stats = home_stats
    match.away_team_stats = away_stats
    match.player_stats = player_stats
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    match.apply_correction(
        correction_id="corr-1",
        changes=[{"op": "update_score", "home_score": 70, "away_score": 68}],
        approved_at=datetime.utcnow(),
        approver_id="admin-1",
        reason="Score correction",
    )

    assert match.version == 3
    assert match.score_summary.home_score == 70
    assert match.collect_events()


def test_correction_update_score_requires_both_scores():
    match = make_match()
    score = ScoreSummary(
        home_score=70,
        away_score=68,
        periods=(PeriodScore(period=1, home=35, away=34), PeriodScore(period=2, home=35, away=34)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=70,
        points_against=68,
        field_goals_made=25,
        field_goals_attempted=55,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=16,
        turnovers=11,
        rebounds=36,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=68,
        points_against=70,
        field_goals_made=24,
        field_goals_attempted=57,
        three_points_made=6,
        three_points_attempted=17,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=13,
        rebounds=33,
    )
    match.score_summary = score
    match.home_team_stats = home_stats
    match.away_team_stats = away_stats
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    with pytest.raises(InvalidCorrection, match="home_score"):
        match.apply_correction(
            correction_id="corr-1",
            changes=[{"op": "update_score"}],
            approved_at=datetime.utcnow(),
            approver_id="admin-1",
            reason="Missing scores",
        )


def test_correction_updates_player_stat():
    match = make_match()
    score = ScoreSummary(
        home_score=70,
        away_score=68,
        periods=(PeriodScore(period=1, home=35, away=34), PeriodScore(period=2, home=35, away=34)),
    )
    home_stats = TeamStats(
        team_external_id="team-home",
        points_for=70,
        points_against=68,
        field_goals_made=25,
        field_goals_attempted=55,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=16,
        turnovers=11,
        rebounds=36,
    )
    away_stats = TeamStats(
        team_external_id="team-away",
        points_for=68,
        points_against=70,
        field_goals_made=24,
        field_goals_attempted=57,
        three_points_made=6,
        three_points_attempted=17,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=13,
        rebounds=33,
    )
    match.score_summary = score
    match.home_team_stats = home_stats
    match.away_team_stats = away_stats
    match.player_stats = (
        PlayerStats(
            player_external_id="pl-1",
            team_external_id="team-home",
            points=20,
            rebounds=8,
            assists=4,
        ),
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    match.apply_correction(
        correction_id="corr-2",
        changes=[{"op": "update_player_stat", "player_external_id": "pl-1", "values": {"points": 22}}],
        approved_at=datetime.utcnow(),
        approver_id="admin-1",
        reason="Stat correction",
    )

    assert match.player_stats[0].points == 22


def test_correction_rejects_unknown_player():
    match = make_match()
    score = ScoreSummary(
        home_score=70,
        away_score=68,
        periods=(PeriodScore(period=1, home=35, away=34), PeriodScore(period=2, home=35, away=34)),
    )
    match.score_summary = score
    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=70,
        points_against=68,
        field_goals_made=25,
        field_goals_attempted=55,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=16,
        turnovers=11,
        rebounds=36,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=68,
        points_against=70,
        field_goals_made=24,
        field_goals_attempted=57,
        three_points_made=6,
        three_points_attempted=17,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=13,
        rebounds=33,
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    with pytest.raises(InvalidCorrection, match="unknown player"):
        match.apply_correction(
            correction_id="corr-3",
            changes=[{"op": "update_player_stat", "player_external_id": "unknown", "values": {"points": 10}}],
            approved_at=datetime.utcnow(),
            approver_id="admin-1",
            reason="Bad player",
        )


def test_correction_rejects_unsupported_operation():
    match = make_match()
    score = ScoreSummary(
        home_score=70,
        away_score=68,
        periods=(PeriodScore(period=1, home=35, away=34), PeriodScore(period=2, home=35, away=34)),
    )
    match.score_summary = score
    match.home_team_stats = TeamStats(
        team_external_id="team-home",
        points_for=70,
        points_against=68,
        field_goals_made=25,
        field_goals_attempted=55,
        three_points_made=7,
        three_points_attempted=18,
        free_throws_made=13,
        free_throws_attempted=16,
        turnovers=11,
        rebounds=36,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away",
        points_for=68,
        points_against=70,
        field_goals_made=24,
        field_goals_attempted=57,
        three_points_made=6,
        three_points_attempted=17,
        free_throws_made=14,
        free_throws_attempted=18,
        turnovers=13,
        rebounds=33,
    )
    match.finalize(finalized_at=datetime.utcnow(), actor_id="admin-1")

    with pytest.raises(InvalidCorrection, match="Unsupported"):
        match.apply_correction(
            correction_id="corr-4",
            changes=[{"op": "delete_match"}],
            approved_at=datetime.utcnow(),
            approver_id="admin-1",
            reason="Invalid op",
        )


def test_invalid_correction_on_non_finalized_match():
    match = make_match()
    with pytest.raises(InvalidCorrection):
        match.apply_correction(
            correction_id="corr-1",
            changes=[{"op": "update_score", "home_score": 71, "away_score": 68}],
            approved_at=datetime.utcnow(),
            approver_id="admin-1",
            reason="Score correction",
        )


@given(
    home1=st.integers(min_value=0, max_value=100),
    away1=st.integers(min_value=0, max_value=100),
    home2=st.integers(min_value=0, max_value=100),
    away2=st.integers(min_value=0, max_value=100),
)
def test_score_summary_periods_sum_to_final(home1, away1, home2, away2):
    total_home = home1 + home2
    total_away = away1 + away2
    summary = ScoreSummary(
        home_score=total_home,
        away_score=total_away,
        periods=(PeriodScore(period=1, home=home1, away=away1), PeriodScore(period=2, home=home2, away=away2)),
    )
    assert summary.home_score == total_home
    assert summary.away_score == total_away
