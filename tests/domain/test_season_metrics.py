"""FASE 23.4 — Season Metrics tests (application + domain reference).

Exercises SeasonMetricsService via the InMemoryMatchStatsRepository and the
pure-Python reference derivation in ``domain.statistics.metrics``. The
InMemory backend keeps the suite fast and fully offline; the mathematical
consistency of the derived per-game read models is asserted here. SQL
backends are exercised separately in tests/postgres/test_season_metric_sql.py.
"""

from __future__ import annotations

import pytest

from feb_score.application.repositories.in_memory import InMemoryMatchStatsRepository
from feb_score.application.use_cases.season_metrics_service import SeasonMetricsService
from feb_score.domain.statistics.metrics import player_metrics, team_metrics
from feb_score.domain.statistics.model import (
    PlayerStats,
    SeasonPlayerMetrics,
    SeasonPlayerStats,
    SeasonTeamMetrics,
    SeasonTeamStats,
    TeamStats,
)
from feb_score.domain.value_objects import SeasonCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SC_2526 = SeasonCode("2025-2026")
SC_2425 = SeasonCode("2024-2025")


def _ps(pid: str, pts: int, reb: int = 0, ast: int = 0,
        stl: int = 0, blk: int = 0, to: int = 0, minutes: float = 0.0) -> PlayerStats:
    return PlayerStats(
        player_external_id=pid,
        team_external_id="TX",
        points=pts, rebounds=reb, assists=ast,
        steals=stl, blocks=blk, turnovers=to, minutes=minutes,
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
    """Service pre-loaded with player data for 2025-2026 (2 games)."""
    repo = InMemoryMatchStatsRepository()
    repo.save_player_stats("M1", SC_2526, [
        _ps("PA", pts=30, reb=5, ast=3, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PB", pts=20, reb=8, ast=7, stl=1, blk=0, to=2, minutes=25.0),
        _ps("PC", pts=15, reb=3, ast=10, stl=0, blk=2, to=4, minutes=20.0),
    ])
    repo.save_player_stats("M2", SC_2526, [
        _ps("PA", pts=20, reb=4, ast=2, stl=3, blk=0, to=1, minutes=28.0),
        _ps("PB", pts=25, reb=7, ast=5, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PC", pts=10, reb=2, ast=8, stl=1, blk=0, to=2, minutes=18.0),
        _ps("PD", pts=5, reb=1, ast=1, stl=0, blk=0, to=1, minutes=10.0),
    ])
    # other season — must not contaminate 2025-2026
    repo.save_player_stats("M3", SC_2425, [
        _ps("PA", pts=999, reb=999, ast=999, stl=99, blk=99, to=99, minutes=99.0),
    ])
    return SeasonMetricsService(repo)


@pytest.fixture
def svc_team():
    """Service pre-loaded with team data for 2025-2026 (3 games)."""
    repo = InMemoryMatchStatsRepository()
    repo.save_team_stats("M1", SC_2526, [
        _ts("T1", pf=80, pa=70),
        _ts("T2", pf=70, pa=80),
    ])
    repo.save_team_stats("M2", SC_2526, [
        _ts("T1", pf=75, pa=90),
        _ts("T2", pf=90, pa=75),
    ])
    repo.save_team_stats("M3", SC_2526, [
        _ts("T1", pf=85, pa=60),
        _ts("T2", pf=60, pa=85),
    ])
    # other season
    repo.save_team_stats("M4", SC_2425, [
        _ts("T1", pf=100, pa=50),
    ])
    return SeasonMetricsService(repo)


# ===========================================================================
# Player metrics tests (1–12)
# ===========================================================================

def test_player_points_per_game(svc_player):
    """Test 1 — points_per_game = total points / games_played."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PA"].points_per_game - 25.0) < 1e-9   # 50 / 2
    assert abs(m["PB"].points_per_game - 22.5) < 1e-9   # 45 / 2
    assert abs(m["PC"].points_per_game - 12.5) < 1e-9   # 25 / 2
    assert abs(m["PD"].points_per_game - 5.0) < 1e-9    # 5 / 1


def test_player_rebounds_assists_per_game(svc_player):
    """Test 2 — rebounds and assists per game."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PA"].rebounds_per_game - 4.5) < 1e-9   # 9 / 2
    assert abs(m["PA"].assists_per_game - 2.5) < 1e-9    # 5 / 2
    assert abs(m["PC"].rebounds_per_game - 2.5) < 1e-9   # 5 / 2
    assert abs(m["PC"].assists_per_game - 9.0) < 1e-9    # 18 / 2


def test_player_steals_blocks_turnovers_per_game(svc_player):
    """Test 3 — steals, blocks and turnovers per game."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PA"].steals_per_game - 2.5) < 1e-9   # 5 / 2
    assert abs(m["PA"].blocks_per_game - 0.5) < 1e-9   # 1 / 2
    assert abs(m["PA"].turnovers_per_game - 2.0) < 1e-9  # 4 / 2
    assert abs(m["PC"].turnovers_per_game - 3.0) < 1e-9  # 6 / 2


def test_player_minutes_per_game(svc_player):
    """Test 4 — minutes per game from float minutes total."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PA"].minutes_per_game - 29.0) < 1e-9   # 58.0 / 2
    assert abs(m["PD"].minutes_per_game - 10.0) < 1e-9   # 10.0 / 1


def test_player_games_played_is_match_count(svc_player):
    """Test 5 — games_played equals the number of matches recorded."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert m["PA"].games_played == 2
    assert m["PB"].games_played == 2
    assert m["PC"].games_played == 2
    assert m["PD"].games_played == 1


def test_player_totals_repeated_in_read_model(svc_player):
    """Test 6 — read model carries the raw season totals self-contained."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert m["PA"].points == 50 and m["PA"].rebounds == 9 and m["PA"].assists == 5
    assert m["PA"].steals == 5 and m["PA"].blocks == 1 and m["PA"].turnovers == 4
    assert abs(m["PA"].minutes - 58.0) < 1e-9


def test_player_single_game_per_game_equals_total(svc_player):
    """Test 7 — a single-game player has per-game == total."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PD"].points_per_game - 5.0) < 1e-9
    assert abs(m["PD"].rebounds_per_game - 1.0) < 1e-9
    assert abs(m["PD"].assists_per_game - 1.0) < 1e-9


def test_player_zero_games_safe_division():
    """Test 8 — a zero-games aggregate yields 0.0 per-game (safe division)."""
    agg = SeasonPlayerStats(
        player_external_id="PX", season_code=str(SC_2526), games_played=0,
        points=100, rebounds=10, assists=5, steals=1, blocks=1, turnovers=2, minutes=0.0,
    )
    m = player_metrics(agg)
    assert m.games_played == 0
    assert m.points_per_game == 0.0 and m.rebounds_per_game == 0.0
    assert m.assists_per_game == 0.0 and m.turnovers_per_game == 0.0
    assert m.minutes_per_game == 0.0


def test_player_season_isolation(svc_player):
    """Test 9 — other-season rows never leak into 2025-2026 metrics."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert "PA" in m and m["PA"].points == 50
    assert set(m) == {"PA", "PB", "PC", "PD"}


def test_player_deterministic_ordering(svc_player):
    """Test 10 — metrics are ordered deterministically by player_external_id."""
    ids = [e.player_external_id for e in svc_player.list_season_player_metrics(SC_2526)]
    assert ids == sorted(ids)


def test_player_full_precision_no_rounding(svc_player):
    """Test 11 — per-game values keep full float precision (no rounding)."""
    m = {e.player_external_id: e for e in svc_player.list_season_player_metrics(SC_2526)}
    assert abs(m["PA"].steals_per_game - 2.5) < 1e-9
    assert abs(m["PA"].points_per_game - 25.0) < 1e-9
    assert abs(m["PB"].points_per_game - 22.5) < 1e-9


def test_player_empty_season_returns_empty():
    """Test 12 — a season with no data yields an empty list."""
    svc = SeasonMetricsService(InMemoryMatchStatsRepository())
    assert svc.list_season_player_metrics("2030-2031") == []


# ===========================================================================
# Team metrics tests (1–12)
# ===========================================================================

def test_team_points_per_game(svc_team):
    """Test 1 — points_per_game = points_for / games_played."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].points_per_game - 80.0) < 1e-9    # 240 / 3
    assert abs(m["T2"].points_per_game - 220.0 / 3) < 1e-9


def test_team_points_against_per_game(svc_team):
    """Test 2 — points_against_per_game = points_against / games_played."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].points_against_per_game - 220.0 / 3) < 1e-9
    assert abs(m["T2"].points_against_per_game - 80.0) < 1e-9


def test_team_point_difference_per_game(svc_team):
    """Test 3 — point_difference_per_game may be negative."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].point_difference_per_game - (20.0 / 3)) < 1e-9  # +20 / 3
    assert abs(m["T2"].point_difference_per_game - (-20.0 / 3)) < 1e-9  # -20 / 3
    assert m["T2"].point_difference_per_game < 0


def test_team_win_percentage_is_percentage(svc_team):
    """Test 4 — win_percentage is wins/games_played*100 (0..100), not a fraction."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].win_percentage - 200.0 / 3) < 1e-9  # 2/3*100
    assert abs(m["T2"].win_percentage - 100.0 / 3) < 1e-9  # 1/3*100
    assert 0.0 <= m["T1"].win_percentage <= 100.0


def test_team_wins_losses_from_results(svc_team):
    """Test 5 — wins/losses derived from points_for vs points_against."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert (m["T1"].wins, m["T1"].losses) == (2, 1)
    assert (m["T2"].wins, m["T2"].losses) == (1, 2)


def test_team_games_played(svc_team):
    """Test 6 — games_played equals the number of matches."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert m["T1"].games_played == 3
    assert m["T2"].games_played == 3


def test_team_field_goals_per_game(svc_team):
    """Test 7 — field goals made/attempted per game."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].field_goals_made_per_game - 10.0) < 1e-9       # 30 / 3
    assert abs(m["T1"].field_goals_attempted_per_game - 20.0) < 1e-9  # 60 / 3


def test_team_three_points_per_game(svc_team):
    """Test 8 — three-pointers made/attempted per game."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].three_points_made_per_game - 3.0) < 1e-9       # 9 / 3
    assert abs(m["T1"].three_points_attempted_per_game - 8.0) < 1e-9  # 24 / 3


def test_team_free_throws_per_game(svc_team):
    """Test 9 — free throws made/attempted per game."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].free_throws_made_per_game - 4.0) < 1e-9       # 12 / 3
    assert abs(m["T1"].free_throws_attempted_per_game - 6.0) < 1e-9  # 18 / 3


def test_team_turnovers_rebounds_per_game(svc_team):
    """Test 10 — turnovers and rebounds per game."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert abs(m["T1"].turnovers_per_game - 5.0) < 1e-9   # 15 / 3
    assert abs(m["T1"].rebounds_per_game - 20.0) < 1e-9   # 60 / 3


def test_team_season_isolation_and_ordering(svc_team):
    """Test 11 — other-season rows excluded; ordering deterministic."""
    m = {e.team_external_id: e for e in svc_team.list_season_team_metrics(SC_2526)}
    assert set(m) == {"T1", "T2"}
    assert m["T1"].points_for == 240  # 2024-2025's 100 must be excluded
    ids = [e.team_external_id for e in svc_team.list_season_team_metrics(SC_2526)]
    assert ids == sorted(ids)


def test_team_empty_season_and_zero_games_safe_division():
    """Test 12 — empty season -> empty list; zero-games aggregate -> 0.0."""
    svc = SeasonMetricsService(InMemoryMatchStatsRepository())
    assert svc.list_season_team_metrics("2030-2031") == []

    agg = SeasonTeamStats(
        team_external_id="TX", season_code=str(SC_2526), games_played=0,
        wins=0, losses=0, points_for=0, points_against=0,
        field_goals_made=0, field_goals_attempted=0,
        three_points_made=0, three_points_attempted=0,
        free_throws_made=0, free_throws_attempted=0,
        turnovers=0, rebounds=0,
    )
    t = team_metrics(agg)
    assert t.points_per_game == 0.0
    assert t.points_against_per_game == 0.0
    assert t.point_difference_per_game == 0.0
    assert t.win_percentage == 0.0
    assert t.rebounds_per_game == 0.0


# ===========================================================================
# Model validation
# ===========================================================================

def test_player_metrics_reject_negative_games():
    with pytest.raises(ValueError, match="games_played must be non-negative"):
        SeasonPlayerMetrics(
            player_external_id="PX", season_code=str(SC_2526), games_played=-1,
            points=0, points_per_game=0.0, rebounds=0, rebounds_per_game=0.0,
            assists=0, assists_per_game=0.0, steals=0, steals_per_game=0.0,
            blocks=0, blocks_per_game=0.0, turnovers=0, turnovers_per_game=0.0,
            minutes=0.0, minutes_per_game=0.0,
        )


def test_player_metrics_reject_negative_per_game():
    with pytest.raises(ValueError, match="points_per_game must be non-negative"):
        SeasonPlayerMetrics(
            player_external_id="PX", season_code=str(SC_2526), games_played=1,
            points=0, points_per_game=-1.0, rebounds=0, rebounds_per_game=0.0,
            assists=0, assists_per_game=0.0, steals=0, steals_per_game=0.0,
            blocks=0, blocks_per_game=0.0, turnovers=0, turnovers_per_game=0.0,
            minutes=0.0, minutes_per_game=0.0,
        )


def test_team_metrics_reject_negative_games():
    kwargs = dict(
        team_external_id="TX", season_code=str(SC_2526), games_played=-1,
        wins=0, losses=0, points_for=0, points_against=0,
        points_per_game=0.0, points_against_per_game=0.0,
        point_difference_per_game=0.0, win_percentage=0.0,
        field_goals_made_per_game=0.0, field_goals_attempted_per_game=0.0,
        three_points_made_per_game=0.0, three_points_attempted_per_game=0.0,
        free_throws_made_per_game=0.0, free_throws_attempted_per_game=0.0,
        turnovers_per_game=0.0, rebounds_per_game=0.0,
    )
    with pytest.raises(ValueError, match="games_played must be non-negative"):
        SeasonTeamMetrics(**kwargs)


def test_team_metrics_allow_negative_point_difference():
    """point_difference_per_game may be negative (unlike other per-game fields)."""
    kwargs = dict(
        team_external_id="TX", season_code=str(SC_2526), games_played=2,
        wins=0, losses=2, points_for=100, points_against=120,
        points_per_game=50.0, points_against_per_game=60.0,
        point_difference_per_game=-10.0, win_percentage=0.0,
        field_goals_made_per_game=0.0, field_goals_attempted_per_game=0.0,
        three_points_made_per_game=0.0, three_points_attempted_per_game=0.0,
        free_throws_made_per_game=0.0, free_throws_attempted_per_game=0.0,
        turnovers_per_game=0.0, rebounds_per_game=0.0,
    )
    SeasonTeamMetrics(**kwargs)  # must not raise