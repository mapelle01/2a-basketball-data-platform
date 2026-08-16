"""FASE 23.2 — Season Team Aggregates tests.

Tests exercise the list_season_team_aggregates operation across all backends
(in-memory mock via SQLite and PostgreSQL) following the same parametrisation
pattern as test_season_player_aggregates.py.

Verifies:
    1. Equipo con varios partidos (games_played, totals).
    2. Victorias y derrotas.
    3. points_for / points_against.
    4. Estadísticas acumuladas (rebounds, turnovers, fg, 3p, ft).
    5. Aislamiento de temporadas.
    6. Determinismo / orden estable.
    7. Múltiples equipos sin mezcla.
    8. Idempotencia (replay no duplica games_played).
    9. Resultado de victoria/derrota por comparación de puntos.
"""

import pytest

from feb_score.domain.statistics.model import TeamStats


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

def _ts(team_id: str, pts_for: int, pts_against: int, **extra) -> TeamStats:
    """Build a minimal TeamStats with sensible defaults for optional fields."""
    defaults = dict(
        field_goals_made=10,
        field_goals_attempted=20,
        three_points_made=3,
        three_points_attempted=8,
        free_throws_made=4,
        free_throws_attempted=6,
        turnovers=5,
        rebounds=20,
    )
    defaults.update(extra)
    return TeamStats(
        team_external_id=team_id,
        points_for=pts_for,
        points_against=pts_against,
        **defaults,
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_single_team_multiple_games(stats_repo):
    """Test 1 — equipo con varios partidos: games_played y totals correctos."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 75, turnovers=3, rebounds=30)])
    stats_repo.save_team_stats("M2", "2025-2026", [_ts("T1", 70, 85, turnovers=7, rebounds=25)])
    stats_repo.save_team_stats("M3", "2025-2026", [_ts("T1", 90, 60, turnovers=4, rebounds=35)])

    results = list(stats_repo.list_season_team_aggregates("2025-2026"))
    assert len(results) == 1
    t1 = results[0]

    assert t1.games_played == 3
    assert t1.points_for == 80 + 70 + 90
    assert t1.points_against == 75 + 85 + 60
    assert t1.turnovers == 3 + 7 + 4
    assert t1.rebounds == 30 + 25 + 35


def test_wins_and_losses(stats_repo):
    """Test 2 — 2 victorias + 1 derrota."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70)])  # win
    stats_repo.save_team_stats("M2", "2025-2026", [_ts("T1", 75, 80)])  # loss
    stats_repo.save_team_stats("M3", "2025-2026", [_ts("T1", 90, 65)])  # win

    results = list(stats_repo.list_season_team_aggregates("2025-2026"))
    t1 = results[0]

    assert t1.games_played == 3
    assert t1.wins == 2
    assert t1.losses == 1
    # invariant enforced by dataclass
    assert t1.wins + t1.losses == t1.games_played


def test_points_for_against(stats_repo):
    """Test 3 — points_for / points_against aggregation."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 82, 78)])
    stats_repo.save_team_stats("M2", "2025-2026", [_ts("T1", 73, 88)])

    t1 = list(stats_repo.list_season_team_aggregates("2025-2026"))[0]

    assert t1.points_for == 82 + 73
    assert t1.points_against == 78 + 88


def test_accumulated_stats(stats_repo):
    """Test 4 — rebounds, turnovers, field goals, three points, free throws."""
    ts_m1 = TeamStats(
        team_external_id="T1",
        points_for=80, points_against=70,
        field_goals_made=25, field_goals_attempted=55,
        three_points_made=8, three_points_attempted=22,
        free_throws_made=14, free_throws_attempted=16,
        turnovers=10, rebounds=40,
    )
    ts_m2 = TeamStats(
        team_external_id="T1",
        points_for=75, points_against=80,
        field_goals_made=20, field_goals_attempted=48,
        three_points_made=6, three_points_attempted=18,
        free_throws_made=23, free_throws_attempted=25,
        turnovers=14, rebounds=35,
    )
    stats_repo.save_team_stats("M1", "2025-2026", [ts_m1])
    stats_repo.save_team_stats("M2", "2025-2026", [ts_m2])

    t1 = list(stats_repo.list_season_team_aggregates("2025-2026"))[0]

    assert t1.field_goals_made == 25 + 20
    assert t1.field_goals_attempted == 55 + 48
    assert t1.three_points_made == 8 + 6
    assert t1.three_points_attempted == 22 + 18
    assert t1.free_throws_made == 14 + 23
    assert t1.free_throws_attempted == 16 + 25
    assert t1.turnovers == 10 + 14
    assert t1.rebounds == 40 + 35


def test_season_isolation(stats_repo):
    """Test 5 — otra temporada no contamina 2025-2026."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70)])
    stats_repo.save_team_stats("M2", "2024-2025", [_ts("T1", 90, 60)])  # other season

    results = list(stats_repo.list_season_team_aggregates("2025-2026"))
    assert len(results) == 1
    assert results[0].games_played == 1
    assert results[0].points_for == 80

    results_old = list(stats_repo.list_season_team_aggregates("2024-2025"))
    assert len(results_old) == 1
    assert results_old[0].points_for == 90


def test_determinism(stats_repo):
    """Test 6 — misma consulta, mismo orden."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("TB", 80, 70), _ts("TA", 70, 80)])
    stats_repo.save_team_stats("M2", "2025-2026", [_ts("TB", 75, 68), _ts("TA", 68, 75)])

    r1 = list(stats_repo.list_season_team_aggregates("2025-2026"))
    r2 = list(stats_repo.list_season_team_aggregates("2025-2026"))

    assert [x.team_external_id for x in r1] == [x.team_external_id for x in r2]
    # alphabetical order: TA before TB
    assert r1[0].team_external_id == "TA"
    assert r1[1].team_external_id == "TB"


def test_multiple_teams_no_mixing(stats_repo):
    """Test 7 — varios equipos no se mezclan entre sí."""
    stats_repo.save_team_stats("M1", "2025-2026", [
        _ts("T1", 80, 70),
        _ts("T2", 70, 80),
    ])
    stats_repo.save_team_stats("M2", "2025-2026", [
        _ts("T1", 90, 85),
        _ts("T2", 85, 90),
    ])

    results = {r.team_external_id: r for r in stats_repo.list_season_team_aggregates("2025-2026")}
    assert len(results) == 2

    t1 = results["T1"]
    t2 = results["T2"]

    assert t1.points_for == 80 + 90
    assert t2.points_for == 70 + 85
    assert t1.wins == 2   # 80>70 and 90>85
    assert t2.wins == 0
    assert t2.losses == 2


def test_replay_does_not_duplicate(stats_repo):
    """Test 8 — re-persistir el mismo partido no incrementa games_played."""
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70)])
    # replay same match_external_id
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70)])

    results = list(stats_repo.list_season_team_aggregates("2025-2026"))
    t1 = results[0]
    # upsert semantics guarantee exactly 1 row per (match, team)
    assert t1.games_played == 1
    assert t1.wins == 1


def test_win_loss_by_points(stats_repo):
    """Test 9 — victoria e derrota derivadas de points_for vs points_against."""
    stats_repo.save_team_stats("M_win",  "2025-2026", [_ts("T1", 100, 50)])  # clear win
    stats_repo.save_team_stats("M_loss", "2025-2026", [_ts("T1", 50, 100)])  # clear loss

    t1 = list(stats_repo.list_season_team_aggregates("2025-2026"))[0]
    assert t1.wins == 1
    assert t1.losses == 1
    assert t1.games_played == 2


def test_math_consistency(stats_repo):
    """Validación matemática: SUM(games_played) == total team-match participations.

    Para N partidos con 2 equipos cada uno:
        SUM(games_played) == 2 * N
        SUM(wins) == N
        SUM(losses) == N
    """
    # 3 matches, each with 2 teams
    stats_repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    stats_repo.save_team_stats("M2", "2025-2026", [_ts("T1", 75, 90), _ts("T2", 90, 75)])
    stats_repo.save_team_stats("M3", "2025-2026", [_ts("T1", 85, 70), _ts("T2", 70, 85)])

    results = list(stats_repo.list_season_team_aggregates("2025-2026"))
    total_games = sum(r.games_played for r in results)
    total_wins  = sum(r.wins for r in results)
    total_losses = sum(r.losses for r in results)

    # 3 matches * 2 teams each = 6 team-match participations
    assert total_games == 6
    # each match produces exactly 1 win and 1 loss across both teams
    assert total_wins == 3
    assert total_losses == 3
