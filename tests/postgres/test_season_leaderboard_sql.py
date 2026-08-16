"""FASE 23.3 — Season Leaderboard tests across SQL backends.

Exercises ``list_season_player_leaderboard`` / ``list_season_team_leaderboard``
on SQLite and PostgreSQL (parametrised ``backend`` fixture), asserting that the
SQL-resolved ranking (ROW_NUMBER) matches the pure-Python reference
implementation and honours season isolation, positional ranks and limits.
"""

import pytest

from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.statistics.ranking import rank_player_entries, rank_team_entries


# ---------------------------------------------------------------------------
# local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(backend):
    return backend.make_db()


@pytest.fixture
def stats_repo(backend, db):
    return backend.repo(db, "stats")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ps(pid: str, pts: int, reb: int = 0, ast: int = 0,
        stl: int = 0, blk: int = 0, to: int = 0, minutes: float = 0.0) -> PlayerStats:
    return PlayerStats(
        player_external_id=pid,
        team_external_id="TX",
        points=pts, rebounds=reb, assists=ast,
        steals=stl, blocks=blk, turnovers=to, minutes=minutes,
    )


def _ts(tid: str, pf: int, pa: int) -> TeamStats:
    return TeamStats(
        team_external_id=tid,
        points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20,
        three_points_made=3, three_points_attempted=8,
        free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
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
        _ts("T1", 80, 70),   # T1 win
        _ts("T2", 70, 80),   # T2 loss
    ])
    stats_repo.save_team_stats("M2", "2025-2026", [
        _ts("T1", 75, 90),   # T1 loss
        _ts("T2", 90, 75),   # T2 win
    ])
    stats_repo.save_team_stats("M3", "2025-2026", [
        _ts("T1", 85, 60),   # T1 win
        _ts("T2", 60, 85),   # T2 loss
    ])
    # other season
    stats_repo.save_team_stats("M4", "2024-2025", [
        _ts("T1", 100, 50),
    ])


# ---------------------------------------------------------------------------
# player leaderboard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metric", [
    "points", "rebounds", "assists", "steals", "blocks", "turnovers", "games_played",
])
def test_player_leaderboard_matches_reference(stats_repo, metric):
    _load(stats_repo)
    sql = list(stats_repo.list_season_player_leaderboard("2025-2026", metric))
    ref = rank_player_entries(
        list(stats_repo.list_season_player_aggregates("2025-2026")), metric
    )
    assert [e.player_external_id for e in sql] == [e.player_external_id for e in ref]
    assert [e.rank for e in sql] == [e.rank for e in ref]
    # positional ranks are consecutive (1..N), never shared
    assert [e.rank for e in sql] == list(range(1, len(sql) + 1))


def test_player_leaderboard_values_match_aggregates(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_player_leaderboard("2025-2026", "points"))
    by_id = {e.player_external_id: e for e in lb}
    assert by_id["PA"].points == 50
    assert by_id["PB"].points == 45
    assert by_id["PC"].points == 25
    assert by_id["PD"].points == 5
    assert by_id["PA"].rank == 1


def test_player_leaderboard_limit_keeps_global_ranks(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_player_leaderboard("2025-2026", "points", limit=2))
    assert len(lb) == 2
    assert [e.rank for e in lb] == [1, 2]
    assert lb[0].player_external_id == "PA"


def test_player_leaderboard_season_isolation(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_player_leaderboard("2025-2026", "points"))
    pa = next(e for e in lb if e.player_external_id == "PA")
    assert pa.points == 50  # 2024-2025 999-pt game not included

    old = list(stats_repo.list_season_player_leaderboard("2024-2025", "points"))
    assert len(old) == 1
    assert old[0].points == 999


def test_invalid_player_metric_raises(stats_repo):
    with pytest.raises(ValueError, match="Unknown player metric"):
        stats_repo.list_season_player_leaderboard("2025-2026", "bogus")


# ---------------------------------------------------------------------------
# team leaderboard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metric", [
    "classification", "points_for", "point_difference", "win_percentage",
])
def test_team_leaderboard_matches_reference(stats_repo, metric):
    _load(stats_repo)
    sql = list(stats_repo.list_season_team_leaderboard("2025-2026", metric))
    ref = rank_team_entries(
        list(stats_repo.list_season_team_aggregates("2025-2026")), metric
    )
    assert [e.team_external_id for e in sql] == [e.team_external_id for e in ref]
    assert [e.rank for e in sql] == [e.rank for e in ref]
    assert [e.rank for e in sql] == list(range(1, len(sql) + 1))


def test_team_leaderboard_derived_fields(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_team_leaderboard("2025-2026", "classification"))
    by_id = {e.team_external_id: e for e in lb}
    t1, t2 = by_id["T1"], by_id["T2"]
    # classification: T1 2W-1L first
    assert lb[0].team_external_id == "T1"
    assert t1.wins == 2 and t1.losses == 1
    assert t1.point_difference == t1.points_for - t1.points_against
    assert abs(t1.win_percentage - 2 / 3) < 1e-9
    assert abs(t2.win_percentage - 1 / 3) < 1e-9


def test_team_leaderboard_limit_keeps_global_ranks(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_team_leaderboard("2025-2026", "classification", limit=1))
    assert len(lb) == 1
    assert lb[0].rank == 1
    assert lb[0].team_external_id == "T1"


def test_team_leaderboard_season_isolation(stats_repo):
    _load(stats_repo)
    lb = list(stats_repo.list_season_team_leaderboard("2025-2026", "points_for"))
    t1 = next(e for e in lb if e.team_external_id == "T1")
    assert t1.points_for == 240  # 2024-2025 100-pt game not included

    old = list(stats_repo.list_season_team_leaderboard("2024-2025", "classification"))
    assert len(old) == 1
    assert old[0].team_external_id == "T1"
    assert old[0].points_for == 100


def test_team_leaderboard_math_consistency(stats_repo):
    """SUM(games_played) == 2 * matches; SUM(wins) == SUM(losses) == matches."""
    _load(stats_repo)
    lb = list(stats_repo.list_season_team_leaderboard("2025-2026", "classification"))
    assert sum(e.games_played for e in lb) == 6  # 3 matches x 2 teams
    assert sum(e.wins for e in lb) == 3
    assert sum(e.losses for e in lb) == 3


def test_invalid_team_metric_raises(stats_repo):
    with pytest.raises(ValueError, match="Unknown team metric"):
        stats_repo.list_season_team_leaderboard("2025-2026", "bogus")


# ---------------------------------------------------------------------------
# empty / edge
# ---------------------------------------------------------------------------

def test_empty_season_returns_empty(stats_repo):
    _load(stats_repo)
    assert list(stats_repo.list_season_player_leaderboard("2030-2031", "points")) == []
    assert list(stats_repo.list_season_team_leaderboard("2030-2031", "classification")) == []