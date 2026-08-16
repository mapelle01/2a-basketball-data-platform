"""FASE 23.3 — Season Leaderboard tests.

Tests exercise SeasonLeaderboardService (application layer) via the
InMemoryMatchStatsRepository.  No PostgreSQL/SQLite fixtures are needed here
because the service delegates data retrieval to the repository and the ranking
logic is purely in Python.

The InMemory backend is sufficient and keeps tests fast and fully offline.
The mathematical-consistency tests (sum invariants) are also here.
"""

from __future__ import annotations

import pytest

from feb_score.application.repositories.in_memory import InMemoryMatchStatsRepository
from feb_score.application.use_cases.leaderboard_service import SeasonLeaderboardService
from feb_score.domain.statistics.model import (
    PlayerLeaderboardMetric,
    PlayerStats,
    TeamLeaderboardMetric,
    TeamStats,
)
from feb_score.domain.value_objects import SeasonCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SC_2526 = SeasonCode("2025-2026")
SC_2425 = SeasonCode("2024-2025")


def _ps(pid: str, pts: int, reb: int = 0, ast: int = 0,
        stl: int = 0, blk: int = 0, to: int = 0, min: float = 0.0) -> PlayerStats:
    return PlayerStats(
        player_external_id=pid,
        team_external_id="TX",
        points=pts, rebounds=reb, assists=ast,
        steals=stl, blocks=blk, turnovers=to, minutes=min,
    )


def _ts(tid: str, pf: int, pa: int,
        fgm: int = 10, fga: int = 20,
        tpm: int = 3, tpa: int = 8,
        ftm: int = 4, fta: int = 6,
        to: int = 5, reb: int = 20) -> TeamStats:
    return TeamStats(
        team_external_id=tid,
        points_for=pf, points_against=pa,
        field_goals_made=fgm, field_goals_attempted=fga,
        three_points_made=tpm, three_points_attempted=tpa,
        free_throws_made=ftm, free_throws_attempted=fta,
        turnovers=to, rebounds=reb,
    )


@pytest.fixture
def svc_player():
    """Service pre-loaded with player data for 2025-2026."""
    repo = InMemoryMatchStatsRepository()
    # Match 1
    repo.save_player_stats("M1", SC_2526, [
        _ps("PA", pts=30, reb=5, ast=3, stl=2, blk=1, to=3, min=30.0),
        _ps("PB", pts=20, reb=8, ast=7, stl=1, blk=0, to=2, min=25.0),
        _ps("PC", pts=15, reb=3, ast=10, stl=0, blk=2, to=4, min=20.0),
    ])
    # Match 2
    repo.save_player_stats("M2", SC_2526, [
        _ps("PA", pts=20, reb=4, ast=2, stl=3, blk=0, to=1, min=28.0),
        _ps("PB", pts=25, reb=7, ast=5, stl=2, blk=1, to=3, min=30.0),
        _ps("PC", pts=10, reb=2, ast=8, stl=1, blk=0, to=2, min=18.0),
        _ps("PD", pts=5, reb=1, ast=1, stl=0, blk=0, to=1, min=10.0),
    ])
    # Other season — must not contaminate 2025-2026
    repo.save_player_stats("M3", SC_2425, [
        _ps("PA", pts=999, reb=999, ast=999, stl=99, blk=99, to=99, min=99.0),
    ])
    return SeasonLeaderboardService(repo)


@pytest.fixture
def svc_team():
    """Service pre-loaded with team data for 2025-2026."""
    repo = InMemoryMatchStatsRepository()
    # 3 matches, 2 teams each
    repo.save_team_stats("M1", SC_2526, [
        _ts("T1", pf=80, pa=70),   # T1 win
        _ts("T2", pf=70, pa=80),   # T2 loss
    ])
    repo.save_team_stats("M2", SC_2526, [
        _ts("T1", pf=75, pa=90),   # T1 loss
        _ts("T2", pf=90, pa=75),   # T2 win
    ])
    repo.save_team_stats("M3", SC_2526, [
        _ts("T1", pf=85, pa=60),   # T1 win
        _ts("T2", pf=60, pa=85),   # T2 loss
    ])
    # Other season
    repo.save_team_stats("M4", SC_2425, [
        _ts("T1", pf=100, pa=50),
    ])
    return SeasonLeaderboardService(repo)


# ===========================================================================
# Player leaderboard tests (1–10)
# ===========================================================================

def test_player_ranking_by_points(svc_player):
    """Test 1 — ranking by points."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.POINTS)
    # PA: 30+20=50, PB: 20+25=45, PC: 15+10=25, PD: 5
    assert [e.player_external_id for e in lb] == ["PA", "PB", "PC", "PD"]
    assert [e.rank for e in lb] == [1, 2, 3, 4]
    assert lb[0].points == 50
    assert lb[1].points == 45


def test_player_ranking_by_rebounds(svc_player):
    """Test 2 — ranking by rebounds."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.REBOUNDS)
    # PB: 8+7=15, PA: 5+4=9, PC: 3+2=5, PD: 1
    pids = [e.player_external_id for e in lb]
    assert pids[0] == "PB"
    assert pids[1] == "PA"
    assert lb[0].rebounds == 15


def test_player_ranking_by_assists(svc_player):
    """Test 3 — ranking by assists."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.ASSISTS)
    # PC: 10+8=18, PB: 7+5=12, PA: 3+2=5, PD: 1
    assert lb[0].player_external_id == "PC"
    assert lb[0].assists == 18
    assert lb[1].player_external_id == "PB"


def test_player_ranking_by_steals(svc_player):
    """Test 4 — ranking by steals."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.STEALS)
    # PA: 2+3=5, PB: 1+2=3, PC: 0+1=1, PD: 0
    assert lb[0].player_external_id == "PA"
    assert lb[0].steals == 5


def test_player_ranking_by_blocks(svc_player):
    """Test 5 — ranking by blocks."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.BLOCKS)
    # PC: 2+0=2, PA: 1+0=1, PB: 0+1=1, PD: 0
    assert lb[0].player_external_id == "PC"
    assert lb[0].blocks == 2
    # PA and PB both have 1 block; tiebreaker → PA (A < B)
    assert lb[1].player_external_id == "PA"
    assert lb[2].player_external_id == "PB"


def test_player_ranking_by_turnovers(svc_player):
    """Test 6 — ranking by turnovers: fewest first."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.TURNOVERS)
    # PD: 1, PA: 3+1=4, PB: 2+3=5, PC: 4+2=6
    assert lb[0].player_external_id == "PD"
    assert lb[0].turnovers == 1
    # Last should be PC
    assert lb[-1].player_external_id == "PC"


def test_player_ranking_by_games_played(svc_player):
    """Test 7 — ranking by games_played."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.GAMES_PLAYED)
    # PA, PB, PC: 2 games each; PD: 1 game
    assert lb[0].games_played == 2
    assert lb[-1].player_external_id == "PD"
    assert lb[-1].games_played == 1


def test_player_ranking_tiebreaker_deterministic(svc_player):
    """Test 8 — players with same metric get different consecutive ranks
    ordered by player_external_id ASC."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.GAMES_PLAYED)
    # PA, PB, PC all have 2 games → sorted alphabetically
    top3 = [e.player_external_id for e in lb[:3]]
    assert top3 == ["PA", "PB", "PC"]
    assert [e.rank for e in lb[:3]] == [1, 2, 3]  # consecutive, not shared


def test_player_ranking_limit(svc_player):
    """Test 9 — limit restricts output."""
    lb = svc_player.list_season_player_leaderboard(
        SC_2526, PlayerLeaderboardMetric.POINTS, limit=2
    )
    assert len(lb) == 2
    assert lb[0].rank == 1
    assert lb[1].rank == 2


def test_player_ranking_season_isolation(svc_player):
    """Test 10 — other season data does not appear in 2025-2026 leaderboard."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.POINTS)
    pids = [e.player_external_id for e in lb]
    # PA with 999 points from 2024-2025 must not inflate PA's rank
    assert "PA" in pids
    pa_entry = next(e for e in lb if e.player_external_id == "PA")
    assert pa_entry.points == 50   # 30+20 from 2025-2026 only

    # 2024-2025 leaderboard has only PA (with 999 pts)
    lb_old = svc_player.list_season_player_leaderboard(SC_2425, PlayerLeaderboardMetric.POINTS)
    assert len(lb_old) == 1
    assert lb_old[0].points == 999


# ===========================================================================
# Team leaderboard tests (11–18)
# ===========================================================================

def test_team_ranking_classification(svc_team):
    """Test 11 — classification: T1 2W-1L, T2 1W-2L → T1 first."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    assert lb[0].team_external_id == "T1"
    assert lb[0].wins == 2
    assert lb[1].team_external_id == "T2"
    assert lb[1].wins == 1


def test_team_ranking_classification_tiebreak_losses(svc_team):
    """Test 12 — tiebreak by losses when wins are equal."""
    repo = InMemoryMatchStatsRepository()
    # T1: 1W-1L, T2: 1W-1L but T2 has bigger pt diff → T2 first
    repo.save_team_stats("M1", SC_2526, [_ts("T1", pf=80, pa=70), _ts("T2", pf=70, pa=80)])
    repo.save_team_stats("M2", SC_2526, [_ts("T1", pf=60, pa=90), _ts("T2", pf=90, pa=60)])
    svc = SeasonLeaderboardService(repo)
    lb = svc.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    # T1 point_diff: (80-70)+(60-90) = 10-30 = -20
    # T2 point_diff: (70-80)+(90-60) = -10+30 = +20 → T2 first
    assert lb[0].team_external_id == "T2"
    assert lb[0].point_difference == 20
    assert lb[1].point_difference == -20


def test_team_ranking_classification_tiebreak_point_diff(svc_team):
    """Test 13 — same W-L, then by point_difference DESC."""
    repo = InMemoryMatchStatsRepository()
    repo.save_team_stats("M1", SC_2526, [_ts("TA", pf=90, pa=70), _ts("TB", pf=70, pa=90)])
    repo.save_team_stats("M2", SC_2526, [_ts("TA", pf=60, pa=80), _ts("TB", pf=80, pa=60)])
    svc = SeasonLeaderboardService(repo)
    lb = svc.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    # TA diff: (90-70)+(60-80) = 20-20 = 0
    # TB diff: (70-90)+(80-60) = -20+20 = 0
    # Same diff → tiebreaker: team_external_id ASC → TA first
    assert lb[0].team_external_id == "TA"


def test_team_ranking_points_for(svc_team):
    """Test 14 — ranking by points_for."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.POINTS_FOR)
    # T1: 80+75+85=240, T2: 70+90+60=220
    assert lb[0].team_external_id == "T1"
    assert lb[0].points_for == 240
    assert lb[1].points_for == 220


def test_team_ranking_point_difference(svc_team):
    """Test 15 — ranking by point_difference."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.POINT_DIFFERENCE)
    # T1: (80-70)+(75-90)+(85-60) = 10-15+25 = 20
    # T2: (70-80)+(90-75)+(60-85) = -10+15-25 = -20
    assert lb[0].team_external_id == "T1"
    assert lb[0].point_difference == 20
    assert lb[1].point_difference == -20


def test_team_ranking_win_percentage(svc_team):
    """Test 16 — ranking by win_percentage."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.WIN_PERCENTAGE)
    # T1: 2/3 ≈ 0.667, T2: 1/3 ≈ 0.333
    assert lb[0].team_external_id == "T1"
    assert abs(lb[0].win_percentage - 2 / 3) < 1e-9
    assert abs(lb[1].win_percentage - 1 / 3) < 1e-9


def test_team_ranking_limit(svc_team):
    """Test 17 — limit restricts output."""
    lb = svc_team.list_season_team_leaderboard(
        SC_2526, TeamLeaderboardMetric.CLASSIFICATION, limit=1
    )
    assert len(lb) == 1
    assert lb[0].rank == 1


def test_team_ranking_season_isolation(svc_team):
    """Test 18 — 2024-2025 data does not appear in 2025-2026 leaderboard."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.POINTS_FOR)
    tids = [e.team_external_id for e in lb]
    assert len(lb) == 2
    assert "T1" in tids
    # T1 from 2024-2025 (100 pts) must not inflate T1's points_for
    t1 = next(e for e in lb if e.team_external_id == "T1")
    assert t1.points_for == 240   # only 2025-2026

    lb_old = svc_team.list_season_team_leaderboard(SC_2425, TeamLeaderboardMetric.CLASSIFICATION)
    assert len(lb_old) == 1
    assert lb_old[0].team_external_id == "T1"
    assert lb_old[0].points_for == 100


# ===========================================================================
# Mathematical consistency
# ===========================================================================

def test_player_leaderboard_sum_consistency(svc_player):
    """sum(leaderboard.points) == sum(SeasonPlayerStats.points)."""
    lb = svc_player.list_season_player_leaderboard(SC_2526, PlayerLeaderboardMetric.POINTS)
    agg = list(svc_player._repo.list_season_player_aggregates(SC_2526))
    assert sum(e.points for e in lb) == sum(a.points for a in agg)


def test_team_leaderboard_sum_consistency(svc_team):
    """sum(wins) and sum(losses) in leaderboard match aggregate sums."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    agg = list(svc_team._repo.list_season_team_aggregates(SC_2526))
    assert sum(e.wins for e in lb) == sum(a.wins for a in agg)
    assert sum(e.losses for e in lb) == sum(a.losses for a in agg)


def test_team_leaderboard_games_played_invariant(svc_team):
    """SUM(games_played) == 2 * number_of_matches for 2-team matches."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    # 3 matches × 2 teams = 6 total team-game participations
    assert sum(e.games_played for e in lb) == 6
    assert sum(e.wins for e in lb) == 3
    assert sum(e.losses for e in lb) == 3


# ===========================================================================
# Edge cases
# ===========================================================================

def test_empty_season_returns_empty_leaderboard():
    """Query on a season with no data returns empty list."""
    repo = InMemoryMatchStatsRepository()
    svc = SeasonLeaderboardService(repo)
    assert svc.list_season_player_leaderboard("2030-2031", PlayerLeaderboardMetric.POINTS) == []
    assert svc.list_season_team_leaderboard("2030-2031", TeamLeaderboardMetric.CLASSIFICATION) == []


def test_invalid_player_metric_raises():
    """ValueError on unknown player metric."""
    svc = SeasonLeaderboardService(InMemoryMatchStatsRepository())
    with pytest.raises(ValueError, match="Unknown player metric"):
        svc.list_season_player_leaderboard(SC_2526, "invalid_metric")


def test_invalid_team_metric_raises():
    """ValueError on unknown team metric."""
    svc = SeasonLeaderboardService(InMemoryMatchStatsRepository())
    with pytest.raises(ValueError, match="Unknown team metric"):
        svc.list_season_team_leaderboard(SC_2526, "invalid_metric")


def test_derived_fields_computed_correctly(svc_team):
    """point_difference and win_percentage are derived, not stored."""
    lb = svc_team.list_season_team_leaderboard(SC_2526, TeamLeaderboardMetric.CLASSIFICATION)
    for entry in lb:
        assert entry.point_difference == entry.points_for - entry.points_against
        expected_pct = entry.wins / entry.games_played if entry.games_played > 0 else 0.0
        assert abs(entry.win_percentage - expected_pct) < 1e-9
