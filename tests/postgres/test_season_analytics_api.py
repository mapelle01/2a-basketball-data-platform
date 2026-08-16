"""FASE 23.5 — Season Analytics HTTP API cross-backend integration.

Proves the full stack HTTP -> gateway -> SeasonAnalyticsService ->
MatchStatsRepository for BOTH SQL backends (parametrised ``backend`` fixture:
SQLite + PostgreSQL). Each backend gets its own FastAPI app and the same
deterministic dataset; every analytics endpoint must return identical results.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
from feb_score.api.main import create_app

SEASON = "2025-2026"


def _ps(pid, pts, reb=0, ast=0, stl=0, blk=0, to=0, minutes=0.0):
    return PlayerStats(
        player_external_id=pid, team_external_id="TX",
        points=pts, rebounds=reb, assists=ast, steals=stl,
        blocks=blk, turnovers=to, minutes=minutes,
    )


def _ts(tid, pf, pa):
    return TeamStats(
        team_external_id=tid, points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20, three_points_made=3,
        three_points_attempted=8, free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
    )


@pytest.fixture
def api(backend):
    """A FastAPI app over the parametrised backend, pre-loaded with data."""
    db = backend.make_db()
    repo = backend.repo(db, "stats")
    repo.save_player_stats("M1", SEASON, [
        _ps("PA", 30, reb=5, ast=3, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PB", 20, reb=8, ast=7, stl=1, blk=0, to=2, minutes=25.0),
        _ps("PC", 15, reb=3, ast=10, stl=0, blk=2, to=4, minutes=20.0),
    ])
    repo.save_player_stats("M2", SEASON, [
        _ps("PA", 20, reb=4, ast=2, stl=3, blk=0, to=1, minutes=28.0),
        _ps("PB", 25, reb=7, ast=5, stl=2, blk=1, to=3, minutes=30.0),
        _ps("PC", 10, reb=2, ast=8, stl=1, blk=0, to=2, minutes=18.0),
        _ps("PD", 5, reb=1, ast=1, stl=0, blk=0, to=1, minutes=10.0),
    ])
    repo.save_player_stats("M9", "2024-2025", [
        _ps("PA", 999, reb=999, ast=999, stl=99, blk=99, to=99, minutes=99.0),
    ])
    repo.save_team_stats("M1", SEASON, [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    repo.save_team_stats("M2", SEASON, [_ts("T1", 75, 90), _ts("T2", 90, 75)])
    repo.save_team_stats("M9", "2024-2025", [_ts("T1", 100, 50)])

    gateway = backend.gateway(db, logger=RecordingLogger())
    auth = ApiKeyAuthenticationProvider({"system-key": Principal(id="api", role="system")})
    return TestClient(create_app(gateway, logger=RecordingLogger(), auth=auth))


def _ids(body):
    key = "player_external_id" if "player_external_id" in body["items"][0] else "team_external_id"
    return [i[key] for i in body["items"]]


def test_players_endpoint_cross_backend(api):
    assert api.get(f"/v1/seasons/{SEASON}/players").json()["count"] == 4
    body = api.get(f"/v1/seasons/{SEASON}/players", params={"limit": 2}).json()
    assert body["count"] == 2 and _ids(body) == ["PA", "PB"]


def test_player_leaderboard_endpoint_cross_backend(api):
    body = api.get(f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points"}).json()
    assert _ids(body) == ["PA", "PB", "PC", "PD"]
    assert [i["rank"] for i in body["items"]] == [1, 2, 3, 4]
    assert api.get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "bogus"}
    ).status_code == 400


def test_player_metrics_endpoint_cross_backend(api):
    body = api.get(f"/v1/seasons/{SEASON}/players/metrics").json()
    by_id = {i["player_external_id"]: i for i in body["items"]}
    assert abs(by_id["PA"]["points_per_game"] - 25.0) < 1e-9
    assert abs(by_id["PC"]["assists_per_game"] - 9.0) < 1e-9


def test_teams_endpoint_cross_backend(api):
    body = api.get(f"/v1/seasons/{SEASON}/teams").json()
    assert body["count"] == 2 and _ids(body) == ["T1", "T2"]
    lb = api.get(f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "classification"}).json()
    assert _ids(lb) == ["T2", "T1"]  # T2 has the positive point_difference
    metrics = api.get(f"/v1/seasons/{SEASON}/teams/metrics").json()
    by_id = {i["team_external_id"]: i for i in metrics["items"]}
    assert abs(by_id["T1"]["win_percentage"] - 50.0) < 1e-9
    assert abs(by_id["T1"]["point_difference_per_game"] + 2.5) < 1e-9


def test_season_isolation_cross_backend(api):
    cur = api.get(f"/v1/seasons/{SEASON}/players").json()
    assert all(i["season_code"] == SEASON for i in cur["items"])
    other = api.get("/v1/seasons/2024-2025/players").json()
    assert other["count"] == 1 and other["items"][0]["points"] == 999