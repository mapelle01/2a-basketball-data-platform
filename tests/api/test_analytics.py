"""FASE 23.5 — Season Analytics HTTP API tests.

End-to-end (HTTP -> gateway -> SeasonAnalyticsService -> MatchStatsRepository
-> SQLite) coverage of the six read endpoints, parameter validation, season
isolation, limit handling, deterministic ordering and the no-secret-leak
guarantee on internal errors.
"""

from __future__ import annotations

import pytest

from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway
from feb_score.api.auth import ApiKeyAuthenticationProvider
from feb_score.api.main import create_app

from api_helpers import make_test_auth_provider


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
def client(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger())
    app = create_app(gateway, logger=RecordingLogger(), auth=make_test_auth_provider())
    return app, gateway


@pytest.fixture
def seeded(client):
    app, gateway = client
    repo = gateway._stats_repo
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
    # other season — must not contaminate 2025-2026
    repo.save_player_stats("M9", "2024-2025", [
        _ps("PA", 999, reb=999, ast=999, stl=99, blk=99, to=99, minutes=99.0),
    ])

    repo.save_team_stats("M1", SEASON, [
        _ts("T1", 80, 70),
        _ts("T2", 70, 80),
    ])
    repo.save_team_stats("M2", SEASON, [
        _ts("T1", 75, 90),
        _ts("T2", 90, 75),
    ])
    # other season
    repo.save_team_stats("M9", "2024-2025", [
        _ts("T1", 100, 50),
    ])
    return app, gateway


def _tc(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ===========================================================================
# Players (aggregates)
# ===========================================================================

def test_players_200_with_schema(seeded):
    app, _ = seeded
    resp = _tc(app).get(f"/v1/seasons/{SEASON}/players")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"season_code", "count", "items"}
    assert body["season_code"] == SEASON
    assert body["count"] == 4
    assert [i["player_external_id"] for i in body["items"]] == ["PA", "PB", "PC", "PD"]
    item = body["items"][0]
    assert item["points"] == 50 and item["games_played"] == 2
    assert set(item.keys()) == {
        "player_external_id", "season_code", "games_played", "points", "rebounds",
        "assists", "steals", "blocks", "turnovers", "minutes",
    }


def test_players_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players").json()
    by_id = {i["player_external_id"]: i for i in body["items"]}
    assert by_id["PA"]["points"] == 50  # 2024-2025 999-pt game excluded

    other = _tc(app).get("/v1/seasons/2024-2025/players").json()
    assert other["count"] == 1
    assert other["items"][0]["points"] == 999


def test_players_limit(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players", params={"limit": 2}).json()
    assert body["count"] == 2
    assert [i["player_external_id"] for i in body["items"]] == ["PA", "PB"]


def test_players_empty_season(seeded):
    app, _ = seeded
    resp = _tc(app).get("/v1/seasons/2030-2031/players")
    assert resp.status_code == 200
    assert resp.json() == {"season_code": "2030-2031", "count": 0, "items": []}


def test_players_invalid_season_400(seeded):
    app, _ = seeded
    resp = _tc(app).get("/v1/seasons/not-a-season/players")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_players_invalid_limit_400(seeded):
    app, _ = seeded
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players", params={"limit": 0}).status_code == 400
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players", params={"limit": 99999}).status_code == 400


# ===========================================================================
# Player leaderboards
# ===========================================================================

def test_player_leaderboard_points(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points"}
    ).json()
    assert [i["player_external_id"] for i in body["items"]] == ["PA", "PB", "PC", "PD"]
    assert [i["rank"] for i in body["items"]] == [1, 2, 3, 4]
    assert body["items"][0]["points"] == 50


def test_player_leaderboard_assists(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "assists"}
    ).json()
    assert body["items"][0]["player_external_id"] == "PC"  # 18 assists
    assert body["items"][0]["rank"] == 1


def test_player_leaderboard_rebounds(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "rebounds"}
    ).json()
    assert body["items"][0]["player_external_id"] == "PB"  # 15 rebounds


def test_player_leaderboard_limit(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards",
        params={"metric": "points", "limit": 2},
    ).json()
    assert body["count"] == 2
    assert [i["rank"] for i in body["items"]] == [1, 2]
    assert body["items"][0]["player_external_id"] == "PA"


def test_player_leaderboard_invalid_metric_400(seeded):
    app, _ = seeded
    resp = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "bogus"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_player_leaderboard_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points"}
    ).json()
    assert all(i["season_code"] == SEASON for i in body["items"])
    assert body["items"][0]["points"] == 50  # 2024-2025 excluded


# ===========================================================================
# Player metrics
# ===========================================================================

def test_player_metrics_values(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/metrics").json()
    by_id = {i["player_external_id"]: i for i in body["items"]}
    assert abs(by_id["PA"]["points_per_game"] - 25.0) < 1e-9   # 50 / 2
    assert abs(by_id["PA"]["assists_per_game"] - 2.5) < 1e-9   # 5 / 2
    assert abs(by_id["PB"]["rebounds_per_game"] - 7.5) < 1e-9  # 15 / 2
    assert abs(by_id["PC"]["assists_per_game"] - 9.0) < 1e-9   # 18 / 2
    assert abs(by_id["PD"]["points_per_game"] - 5.0) < 1e-9    # single game == total
    assert "points_per_game" in by_id["PA"]


def test_player_metrics_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/metrics").json()
    by_id = {i["player_external_id"]: i for i in body["items"]}
    assert by_id["PA"]["points"] == 50  # 2024-2025 excluded

    other = _tc(app).get("/v1/seasons/2024-2025/players/metrics").json()
    assert other["count"] == 1
    assert abs(other["items"][0]["points_per_game"] - 999.0) < 1e-9


def test_player_metrics_limit(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/metrics", params={"limit": 1}).json()
    assert body["count"] == 1
    assert body["items"][0]["player_external_id"] == "PA"


# ===========================================================================
# Teams
# ===========================================================================

def test_teams_aggregates(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams").json()
    assert body["count"] == 2
    by_id = {i["team_external_id"]: i for i in body["items"]}
    assert by_id["T1"]["games_played"] == 2
    assert by_id["T1"]["wins"] == 1 and by_id["T1"]["losses"] == 1
    assert by_id["T1"]["points_for"] == 155
    assert by_id["T2"]["points_against"] == 155
    assert set(by_id["T1"].keys()) == {
        "team_external_id", "season_code", "games_played", "wins", "losses",
        "points_for", "points_against", "field_goals_made", "field_goals_attempted",
        "three_points_made", "three_points_attempted", "free_throws_made",
        "free_throws_attempted", "turnovers", "rebounds",
    }


def test_teams_classification_leaderboard(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "classification"}
    ).json()
    assert [i["rank"] for i in body["items"]] == [1, 2]
    # T1 1W-1L -5 and T2 1W-1L +5: point_difference DESC puts T2 first
    assert body["items"][0]["team_external_id"] == "T2"
    assert body["items"][0]["point_difference"] == 5
    assert "win_percentage" in body["items"][0]


def test_teams_leaderboard_points_for(seeded):
    app, _ = seeded
    body = _tc(app).get(
        f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "points_for"}
    ).json()
    assert body["items"][0]["team_external_id"] == "T2"  # 160 > 155
    assert body["items"][0]["points_for"] == 160


def test_teams_metrics(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams/metrics").json()
    by_id = {i["team_external_id"]: i for i in body["items"]}
    assert abs(by_id["T1"]["points_per_game"] - 77.5) < 1e-9      # 155 / 2
    assert abs(by_id["T1"]["point_difference_per_game"] + 2.5) < 1e-9
    assert abs(by_id["T1"]["win_percentage"] - 50.0) < 1e-9       # percentage, not fraction
    assert abs(by_id["T1"]["rebounds_per_game"] - 20.0) < 1e-9
    assert set(by_id["T1"].keys()) == {
        "team_external_id", "season_code", "games_played", "wins", "losses",
        "points_for", "points_against", "points_per_game", "points_against_per_game",
        "point_difference_per_game", "win_percentage", "field_goals_made_per_game",
        "field_goals_attempted_per_game", "three_points_made_per_game",
        "three_points_attempted_per_game", "free_throws_made_per_game",
        "free_throws_attempted_per_game", "turnovers_per_game", "rebounds_per_game",
    }


def test_teams_limit_and_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams", params={"limit": 1}).json()
    assert body["count"] == 1
    assert body["items"][0]["team_external_id"] == "T1"

    other = _tc(app).get("/v1/seasons/2024-2025/teams/metrics").json()
    assert other["count"] == 1
    assert other["items"][0]["points_for"] == 100  # 2024-2025 only


def test_teams_invalid_metric_400(seeded):
    app, _ = seeded
    resp = _tc(app).get(
        f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "bogus"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


# ===========================================================================
# Errors / security
# ===========================================================================

def test_internal_error_does_not_leak_secrets(client):
    app, gateway = client
    original = gateway.list_season_player_aggregates

    def boom(season_code, limit=None):
        raise RuntimeError("connection failed: postgresql://user:secret@railway/db")

    gateway.list_season_player_aggregates = boom
    try:
        from fastapi.testclient import TestClient
        resp = TestClient(app, raise_server_exceptions=False).get(f"/v1/seasons/{SEASON}/players")
    finally:
        gateway.list_season_player_aggregates = original
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in body["error"]["message"]
    assert "postgresql" not in body["error"]["message"]


def test_analytics_endpoints_are_public(seeded):
    """Reads are public by design (FASE 11/13): no API key required."""
    app, _ = seeded
    for path in (
        f"/v1/seasons/{SEASON}/players",
        f"/v1/seasons/{SEASON}/players/leaderboards?metric=points",
        f"/v1/seasons/{SEASON}/players/metrics",
        f"/v1/seasons/{SEASON}/teams",
        f"/v1/seasons/{SEASON}/teams/leaderboards?metric=classification",
        f"/v1/seasons/{SEASON}/teams/metrics",
    ):
        assert _tc(app).get(path).status_code == 200, path