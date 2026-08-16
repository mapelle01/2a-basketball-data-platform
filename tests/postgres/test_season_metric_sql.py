"""FASE 23.4 — Season Metrics tests across SQL backends.

Exercises ``list_season_player_metrics`` / ``list_season_team_metrics`` on
SQLite and PostgreSQL (parametrised ``backend`` fixture), asserting that the
SQL-resolved per-game derivation matches the pure-Python reference
(InMemory backend), honours season isolation, and satisfies the season-wide
mathematical consistency invariants.
"""

import pytest

from feb_score.application.repositories.in_memory import InMemoryMatchStatsRepository
from feb_score.domain.statistics.model import PlayerStats, TeamStats


# ---------------------------------------------------------------------------
# local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(backend):
    return backend.make_db()


@pytest.fixture
def stats_repo(backend, db):
    return backend.repo(db, "stats")


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


def _load(stats_repo) -> None:
    """Deterministic dataset with a separate 2024-2025 season."""
    stats_repo.save_player_stats("M1", "2025-2026", [
        _ps("PA", pts=30, reb=5, ast=3, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PB", pts=20, reb=8, ast=7, stl=1, blk=0, to=2, minutes=25.0),
        _ps("PC", pts=15, reb=3, ast=10, stl=0, blk=2, to=4, minutes=20.0),
    ])
    stats_repo.save_player_stats("M2", "2025-2026", [
        _ps("PA", pts=20, reb=4, ast=2, stl=3, blk=0, to=1, minutes=28.0),
        _ps("PB", pts=25, reb=7, ast=5, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PC", pts=10, reb=2, ast=8, stl=1, blk=0, to=2, minutes=18.0),
        _ps("PD", pts=5, reb=1, ast=1, stl=0, blk=0, to=1, minutes=10.0),
    ])
    # other season — must not contaminate 2025-2026
    stats_repo.save_player_stats("M3", "2024-2025", [
        _ps("PA", pts=999, reb=999, ast=999, stl=99, blk=99, to=99, minutes=99.0),
    ])

    stats_repo.save_team_stats("M1", "2025-2026", [
        _ts("T1", 80, 70),
        _ts("T2", 70, 80),
    ])
    stats_repo.save_team_stats("M2", "2025-2026", [
        _ts("T1", 75, 90),
        _ts("T2", 90, 75),
    ])
    stats_repo.save_team_stats("M3", "2025-2026", [
        _ts("T1", 85, 60),
        _ts("T2", 60, 85),
    ])
    # other season
    stats_repo.save_team_stats("M4", "2024-2025", [
        _ts("T1", 100, 50),
    ])


# ---------------------------------------------------------------------------
# player metrics
# ---------------------------------------------------------------------------

def test_player_metrics_match_reference(stats_repo):
    _load(stats_repo)
    sql = list(stats_repo.list_season_player_metrics("2025-2026"))
    mem = InMemoryMatchStatsRepository()
    _load(mem)
    ref = {m.player_external_id: m for m in mem.list_season_player_metrics("2025-2026")}

    assert [m.player_external_id for m in sql] == sorted(ref)
    for m in sql:
        r = ref[m.player_external_id]
        assert m.games_played == r.games_played
        assert m.points == r.points and m.rebounds == r.rebounds and m.assists == r.assists
        assert m.steals == r.steals and m.blocks == r.blocks and m.turnovers == r.turnovers
        assert abs(m.minutes - r.minutes) < 1e-9
        for f in ("points_per_game", "rebounds_per_game", "assists_per_game",
                  "steals_per_game", "blocks_per_game", "turnovers_per_game",
                  "minutes_per_game"):
            assert abs(getattr(m, f) - getattr(r, f)) < 1e-9, (m.player_external_id, f)


def test_player_metrics_known_values(stats_repo):
    _load(stats_repo)
    by_id = {m.player_external_id: m for m in stats_repo.list_season_player_metrics("2025-2026")}
    assert by_id["PA"].games_played == 2
    assert abs(by_id["PA"].points_per_game - 25.0) < 1e-9
    assert abs(by_id["PA"].assists_per_game - 2.5) < 1e-9
    assert abs(by_id["PD"].minutes_per_game - 10.0) < 1e-9


def test_player_metrics_season_isolation(stats_repo):
    _load(stats_repo)
    cur = {m.player_external_id: m for m in stats_repo.list_season_player_metrics("2025-2026")}
    assert set(cur) == {"PA", "PB", "PC", "PD"}
    assert cur["PA"].points == 50  # 2024-2025 999-pt game excluded

    old = list(stats_repo.list_season_player_metrics("2024-2025"))
    assert len(old) == 1
    assert old[0].points == 999
    assert abs(old[0].points_per_game - 999.0) < 1e-9


# ---------------------------------------------------------------------------
# team metrics
# ---------------------------------------------------------------------------

def test_team_metrics_match_reference(stats_repo):
    _load(stats_repo)
    sql = list(stats_repo.list_season_team_metrics("2025-2026"))
    mem = InMemoryMatchStatsRepository()
    _load(mem)
    ref = {m.team_external_id: m for m in mem.list_season_team_metrics("2025-2026")}

    assert [m.team_external_id for m in sql] == sorted(ref)
    for m in sql:
        r = ref[m.team_external_id]
        assert m.games_played == r.games_played
        assert (m.wins, m.losses) == (r.wins, r.losses)
        assert (m.points_for, m.points_against) == (r.points_for, r.points_against)
        for f in ("points_per_game", "points_against_per_game", "point_difference_per_game",
                  "win_percentage", "field_goals_made_per_game", "field_goals_attempted_per_game",
                  "three_points_made_per_game", "three_points_attempted_per_game",
                  "free_throws_made_per_game", "free_throws_attempted_per_game",
                  "turnovers_per_game", "rebounds_per_game"):
            assert abs(getattr(m, f) - getattr(r, f)) < 1e-9, (m.team_external_id, f)


def test_team_metrics_win_percentage_is_percentage(stats_repo):
    _load(stats_repo)
    by_id = {m.team_external_id: m for m in stats_repo.list_season_team_metrics("2025-2026")}
    assert abs(by_id["T1"].win_percentage - 200.0 / 3) < 1e-9   # 2W-1L -> 66.66...
    assert abs(by_id["T2"].win_percentage - 100.0 / 3) < 1e-9   # 1W-2L -> 33.33...
    assert by_id["T2"].point_difference_per_game < 0


def test_team_metrics_consistency_invariants(stats_repo):
    """SUM(games_played)=2*matches; SUM(wins)=SUM(losses)=matches; pg*gp ~ totals."""
    _load(stats_repo)
    team_metrics = list(stats_repo.list_season_team_metrics("2025-2026"))
    assert sum(m.games_played for m in team_metrics) == 6
    assert sum(m.wins for m in team_metrics) == 3
    assert sum(m.losses for m in team_metrics) == 3
    for m in team_metrics:
        assert abs(m.points_per_game * m.games_played - m.points_for) < 1e-9
        assert abs(m.points_against_per_game * m.games_played - m.points_against) < 1e-9
        assert abs(m.point_difference_per_game * m.games_played
                   - (m.points_for - m.points_against)) < 1e-9
        assert abs(m.win_percentage - (m.wins / m.games_played * 100.0)) < 1e-9


def test_team_metrics_season_isolation(stats_repo):
    _load(stats_repo)
    cur = {m.team_external_id: m for m in stats_repo.list_season_team_metrics("2025-2026")}
    assert set(cur) == {"T1", "T2"}
    assert cur["T1"].points_for == 240  # 2024-2025 100-pt game excluded

    old = list(stats_repo.list_season_team_metrics("2024-2025"))
    assert len(old) == 1
    assert old[0].team_external_id == "T1"
    assert old[0].points_for == 100


# ---------------------------------------------------------------------------
# empty / edge
# ---------------------------------------------------------------------------

def test_empty_season_returns_empty(stats_repo):
    _load(stats_repo)
    assert list(stats_repo.list_season_player_metrics("2030-2031")) == []
    assert list(stats_repo.list_season_team_metrics("2030-2031")) == []