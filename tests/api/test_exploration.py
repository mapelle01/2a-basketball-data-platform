"""FASE 24 — Match & Player Exploration HTTP API tests.

End-to-end (HTTP -> gateway -> ExplorationService -> repositories -> SQLite)
coverage of the enriched match detail (24.1), player/team season profiles
(24.2/24.3), the three search endpoints (24.4), parameter validation, season
isolation, deterministic ordering, route-order safety and the no-secret-leak
guarantee on internal errors.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from feb_score.domain.match.model import Match
from feb_score.domain.player.model import Player
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PlayerId,
    SeasonCode,
    TeamId,
)
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway
from feb_score.api.auth import ApiKeyAuthenticationProvider
from feb_score.api.main import create_app

from api_helpers import auth_header, create_payload, make_test_auth_provider

SEASON = "2025-2026"


def _ps(pid, team, pts):
    return PlayerStats(
        player_external_id=pid, team_external_id=team, points=pts,
        rebounds=2, assists=1, steals=1, blocks=0, turnovers=0, minutes=25.0,
    )


def _ts(tid, pf, pa):
    return TeamStats(
        team_external_id=tid, points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20, three_points_made=3,
        three_points_attempted=8, free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
    )


def _match(external_id, round_number, home, away, competition="feb-comp", season=SEASON):
    return Match(
        external_id=ExternalId(external_id),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId(competition),
        season_code=SeasonCode(season),
        round_number=round_number,
        home_team_id=ExternalId(home),
        away_team_id=ExternalId(away),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
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
    match_repo = gateway._match_repo
    stats_repo = gateway._stats_repo
    player_repo = gateway._player_repo
    team_repo = gateway._team_repo

    # ---- matches (rounds 1,1,2)
    match_repo.save(_match("M1", 1, "T1", "T2"))
    match_repo.save(_match("M2", 1, "T1", "T3"))
    match_repo.save(_match("M3", 2, "T1", "T2"))
    # other season + other competition — isolation guards
    match_repo.save(_match("M9", 1, "T1", "T2", competition="feb-comp", season="2024-2025"))
    match_repo.save(_match("M7", 1, "T1", "T2", competition="other-comp"))

    # ---- team stats
    stats_repo.save_team_stats("M1", SEASON, [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    stats_repo.save_team_stats("M2", SEASON, [_ts("T1", 90, 75), _ts("T3", 75, 90)])
    stats_repo.save_team_stats("M3", SEASON, [_ts("T1", 60, 65), _ts("T2", 65, 60)])
    stats_repo.save_team_stats("M9", "2024-2025", [_ts("T1", 100, 50)])

    # ---- player stats
    stats_repo.save_player_stats("M1", SEASON, [_ps("PA", "T1", 22), _ps("PB", "T2", 15)])
    stats_repo.save_player_stats("M2", SEASON, [_ps("PA", "T1", 30), _ps("PC", "T3", 12)])
    stats_repo.save_player_stats("M3", SEASON, [_ps("PA", "T1", 18)])
    stats_repo.save_player_stats("M9", "2024-2025", [_ps("PA", "T1", 99)])

    # ---- stats-only identities: PX/T5 have NO catalog record -> derived profile
    stats_repo.save_player_stats("M3", SEASON, [_ps("PX", "T1", 9)])
    stats_repo.save_team_stats("M3", SEASON, [_ts("T5", 41, 39)])

    # ---- players (with registrations) + teams
    def make_player(pid, name, team, dorsal):
        player = Player(external_id=ExternalId(pid), player_id=PlayerId(str(uuid4())), name=name)
        player.register_for_team(team, SeasonCode(SEASON), dorsal=dorsal)
        return player

    player_repo.save(make_player("PA", "Ana López", "T1", 7))
    player_repo.save(make_player("PB", "Bruno García", "T2", 11))
    player_repo.save(make_player("PC", "Carlos López", "T3", 5))
    # registered but with NO stats in the season — profile must not invent data
    player_repo.save(make_player("PZ", "Zoe SinDatos", "T1", 33))

    team_repo.save(Team(external_id=ExternalId("T1"), team_id=TeamId(str(uuid4())), name="Club Uno"))
    team_repo.save(Team(external_id=ExternalId("T2"), team_id=TeamId(str(uuid4())), name="Club Dos"))
    team_repo.save(Team(external_id=ExternalId("T3"), team_id=TeamId(str(uuid4())), name="Club Tres"))
    # a team with no matches/stats at all — profile must not invent data
    team_repo.save(Team(external_id=ExternalId("T4"), team_id=TeamId(str(uuid4())), name="Club Cuatro"))
    return app, gateway


def _tc(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ===========================================================================
# 24.1 — Match detail (enriched existing endpoint)
# ===========================================================================

def test_match_detail_includes_boxscore(seeded):
    app, _ = seeded
    resp = _tc(app).get("/v1/matches/M1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["external_id"] == "M1"
    assert body["season_code"] == SEASON
    assert body["round_number"] == 1
    assert body["status"] == "SCHEDULED"
    # boxscore projection from the stats tables, deterministically ordered
    assert [t["team_external_id"] for t in body["team_stats"]] == ["T1", "T2"]
    assert [t["points_for"] for t in body["team_stats"]] == [80, 70]
    assert [p["player_external_id"] for p in body["player_stats"]] == ["PA", "PB"]
    assert body["player_stats"][0]["points"] == 22
    assert "home_team_id" in body and "away_team_id" in body


def test_match_detail_without_stats_has_empty_boxscore(client):
    app, gateway = client
    gateway._match_repo.save(_match("M0", 1, "T1", "T2"))
    body = _tc(app).get("/v1/matches/M0").json()
    assert body["team_stats"] == []
    assert body["player_stats"] == []


def test_match_detail_404(seeded):
    app, _ = seeded
    resp = _tc(app).get("/v1/matches/absent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_match_detail_round_trip_via_command(client):
    """The enrichment also applies to matches created through the command flow."""
    app, gateway = client
    assert _tc(app).post(
        "/v1/commands/create_or_update_match",
        json={"payload": create_payload()},
        headers=auth_header("system"),
    ).status_code == 200
    gateway._stats_repo.save_team_stats("2513600", "2025-2026", [
        _ts("team-home", 80, 77), _ts("team-away", 77, 80),
    ])
    gateway._stats_repo.save_player_stats("2513600", "2025-2026", [
        _ps("pl-1", "team-home", 22),
    ])
    body = _tc(app).get("/v1/matches/2513600").json()
    assert body["round_number"] == 5
    assert [t["team_external_id"] for t in body["team_stats"]] == ["team-away", "team-home"]
    assert body["player_stats"][0]["player_external_id"] == "pl-1"


# ===========================================================================
# 24.2 — Player profile
# ===========================================================================

def test_player_profile(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/PA").json()
    assert body["player_external_id"] == "PA"
    assert body["name"] == "Ana López"
    assert body["season_code"] == SEASON
    assert body["teams"] == [{"team_external_id": "T1", "dorsal": 7, "role": None}]
    assert body["totals"]["points"] == 70
    assert body["totals"]["games_played"] == 3
    assert abs(body["metrics"]["points_per_game"] - 70 / 3) < 1e-9


def test_player_profile_without_stats_in_season(seeded):
    """A player with no stats in the season gets null totals/metrics (not invented)."""
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/PZ").json()
    assert body["name"] == "Zoe SinDatos"
    assert body["teams"] == [{"team_external_id": "T1", "dorsal": 33, "role": None}]
    assert body["totals"] is None
    assert body["metrics"] is None


def test_player_profile_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get("/v1/seasons/2024-2025/players/PA").json()
    assert body["totals"]["points"] == 99  # only the 2024-2025 stats row
    assert body["teams"] == []  # no registration for that season


def test_player_profile_404_and_400(seeded):
    app, _ = seeded
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players/absent").status_code == 404
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players/absent").json()["error"]["code"] == "NOT_FOUND"
    resp = _tc(app).get("/v1/seasons/not-a-season/players/PA")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_player_profile_derived_from_stats_without_catalog(seeded):
    """A player with stats but no catalog record resolves with name=null."""
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/players/PX").json()
    assert body["player_external_id"] == "PX"
    assert body["name"] is None
    assert body["position"] is None and body["nationality"] is None and body["birth_date"] is None
    # teams derived from the player's BoxScore rows
    assert body["teams"] == [{"team_external_id": "T1", "dorsal": None, "role": None}]
    assert body["totals"]["points"] == 9
    assert body["totals"]["games_played"] == 1
    assert body["metrics"] is not None


def test_player_profile_derived_404_when_no_data_at_all(seeded):
    """404 is reserved for entities with no catalog AND no stats."""
    app, _ = seeded
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players/noone").status_code == 404


# ===========================================================================
# 24.3 — Team profile + round evolution
# ===========================================================================

def test_team_profile_with_evolution(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams/T1").json()
    assert body["team_external_id"] == "T1"
    assert body["name"] == "Club Uno"
    assert body["season_code"] == SEASON
    assert body["totals"]["points_for"] == 230
    assert body["totals"]["wins"] == 2 and body["totals"]["losses"] == 1
    assert abs(body["metrics"]["points_per_game"] - 230 / 3) < 1e-9
    assert body["evolution"] == [
        {"round_number": 1, "games_played": 2, "wins": 2, "losses": 0,
         "points_for": 170, "points_against": 145, "point_difference": 25},
        {"round_number": 2, "games_played": 1, "wins": 0, "losses": 1,
         "points_for": 60, "points_against": 65, "point_difference": -5},
    ]


def test_team_profile_without_stats(seeded):
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams/T4").json()
    assert body["name"] == "Club Cuatro"
    assert body["totals"] is None
    assert body["metrics"] is None
    assert body["evolution"] == []


def test_team_profile_404_and_400(seeded):
    app, _ = seeded
    assert _tc(app).get(f"/v1/seasons/{SEASON}/teams/absent").status_code == 404
    resp = _tc(app).get("/v1/seasons/not-a-season/teams/T1")
    assert resp.status_code == 400


def test_team_profile_derived_from_stats_without_catalog(seeded):
    """A team with stats but no catalog record resolves with name=null."""
    app, _ = seeded
    body = _tc(app).get(f"/v1/seasons/{SEASON}/teams/T5").json()
    assert body["team_external_id"] == "T5"
    assert body["name"] is None
    assert body["season_code"] == SEASON
    assert body["totals"]["points_for"] == 41 and body["totals"]["points_against"] == 39
    assert body["totals"]["games_played"] == 1
    assert body["metrics"] is not None
    assert body["evolution"] == [
        {"round_number": 2, "games_played": 1, "wins": 1, "losses": 0,
         "points_for": 41, "points_against": 39, "point_difference": 2},
    ]


# ===========================================================================
# 24.4 — Search
# ===========================================================================

def test_players_search(seeded):
    app, _ = seeded
    body = _tc(app).get("/v1/players/search", params={"q": "lópez"}).json()
    assert body["q"] == "lópez"
    assert [i["player_external_id"] for i in body["items"]] == ["PA", "PC"]  # case-insensitive
    assert body["items"][0]["name"] == "Ana López"


def test_players_search_case_insensitive_and_limit(seeded):
    app, _ = seeded
    body = _tc(app).get("/v1/players/search", params={"q": "ANA", "limit": 1}).json()
    assert body["count"] == 1
    assert body["items"][0]["player_external_id"] == "PA"


def test_players_search_wildcards_are_literal(seeded):
    app, _ = seeded
    # '%' and '_' must match literally, never as wildcards
    assert _tc(app).get("/v1/players/search", params={"q": "%"}).json()["count"] == 0
    assert _tc(app).get("/v1/players/search", params={"q": "_"}).json()["count"] == 0
    assert _tc(app).get("/v1/players/search", params={"q": "na L"}).json()["count"] == 1


def test_players_search_validation(seeded):
    app, _ = seeded
    resp = _tc(app).get("/v1/players/search", params={"q": " "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert _tc(app).get("/v1/players/search", params={"q": "x", "limit": 0}).status_code == 400
    assert _tc(app).get("/v1/players/search", params={"q": "x", "limit": 99999}).status_code == 400
    assert _tc(app).get("/v1/players/search").status_code == 400


def test_teams_search(seeded):
    app, _ = seeded
    body = _tc(app).get("/v1/teams/search", params={"q": "club"}).json()
    assert [i["team_external_id"] for i in body["items"]] == ["T1", "T2", "T3", "T4"]
    body = _tc(app).get("/v1/teams/search", params={"q": "DOS"}).json()
    assert [i["team_external_id"] for i in body["items"]] == ["T2"]
    assert _tc(app).get("/v1/teams/search", params={"q": "x"}).json()["count"] == 0


def test_matches_search_filters(seeded):
    app, _ = seeded
    get = lambda params: _tc(app).get("/v1/matches/search", params=params).json()
    ids = lambda body: [i["external_id"] for i in body["items"]]

    body = get({"season_code": SEASON})
    assert ids(body) == ["M1", "M2", "M3", "M7"]
    assert body["season_code"] == SEASON and body["count"] == 4

    assert ids(get({"season_code": SEASON, "competition_id": "other-comp"})) == ["M7"]
    assert ids(get({"season_code": SEASON, "round_number": 1})) == ["M1", "M2", "M7"]
    assert ids(get({"season_code": SEASON, "round_number": 2})) == ["M3"]
    # home OR away
    assert ids(get({"season_code": SEASON, "team_external_id": "T3"})) == ["M2"]
    assert ids(get({"season_code": SEASON, "team_external_id": "T2"})) == ["M1", "M3", "M7"]
    assert ids(get({"season_code": SEASON, "q": "M1"})) == ["M1"]
    assert ids(get({"season_code": SEASON, "q": "M", "limit": 2})) == ["M1", "M2"]


def test_matches_search_season_isolation(seeded):
    app, _ = seeded
    body = _tc(app).get("/v1/matches/search", params={"season_code": "2024-2025"}).json()
    assert [i["external_id"] for i in body["items"]] == ["M9"]
    body = _tc(app).get("/v1/matches/search", params={"season_code": "2030-2031"}).json()
    assert body["count"] == 0 and body["items"] == []


def test_matches_search_validation(seeded):
    app, _ = seeded
    assert _tc(app).get("/v1/matches/search").status_code == 400
    resp = _tc(app).get("/v1/matches/search", params={"season_code": "bogus"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"
    assert _tc(app).get(
        "/v1/matches/search", params={"season_code": SEASON, "round_number": 0}
    ).status_code == 400
    assert _tc(app).get(
        "/v1/matches/search", params={"season_code": SEASON, "round_number": -3}
    ).status_code == 400
    assert _tc(app).get(
        "/v1/matches/search", params={"season_code": SEASON, "round_number": "abc"}
    ).status_code == 400
    assert _tc(app).get(
        "/v1/matches/search", params={"season_code": SEASON, "limit": 99999}
    ).status_code == 400


# ===========================================================================
# Route-order safety / determinism / security
# ===========================================================================

def test_analytics_routes_not_shadowed_by_profile_routes(seeded):
    """The {player_external_id} profile route must not shadow /leaderboards or /metrics."""
    app, _ = seeded
    assert _tc(app).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points"}
    ).status_code == 200
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players/metrics").status_code == 200
    assert _tc(app).get(
        f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "classification"}
    ).status_code == 200
    assert _tc(app).get(f"/v1/seasons/{SEASON}/teams/metrics").status_code == 200
    assert _tc(app).get(f"/v1/seasons/{SEASON}/players").status_code == 200


def test_search_routes_not_shadowed_by_external_id_routes(seeded):
    """/v1/players/search must beat /v1/players/{external_id}."""
    app, _ = seeded
    resp = _tc(app).get("/v1/players/search", params={"q": "ana"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_exploration_determinism(seeded):
    app, _ = seeded
    for path in (
        f"/v1/seasons/{SEASON}/players/PA",
        f"/v1/seasons/{SEASON}/teams/T1",
        "/v1/players/search?q=lópez",
        "/v1/teams/search?q=club",
        f"/v1/matches/search?season_code={SEASON}",
        "/v1/matches/M1",
    ):
        first = _tc(app).get(path).json()
        second = _tc(app).get(path).json()
        assert first == second, path


def test_internal_error_does_not_leak_secrets(seeded):
    app, gateway = seeded
    original = gateway.search_players

    def boom(q, limit=None):
        raise RuntimeError("connection failed: postgresql://user:secret@railway/db")

    gateway.search_players = boom
    try:
        resp = TestClient(app, raise_server_exceptions=False).get(
            "/v1/players/search", params={"q": "x"}
        )
    finally:
        gateway.search_players = original
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in body["error"]["message"]
    assert "postgresql" not in body["error"]["message"]


def test_exploration_endpoints_are_public(seeded):
    """Reads are public by design (FASE 11/13): no API key required."""
    app, _ = seeded
    for path in (
        f"/v1/seasons/{SEASON}/players/PA",
        f"/v1/seasons/{SEASON}/teams/T1",
        "/v1/players/search?q=x",
        "/v1/teams/search?q=x",
        f"/v1/matches/search?season_code={SEASON}",
        "/v1/matches/M1",
    ):
        assert _tc(app).get(path).status_code == 200, path


def test_openapi_exposes_all_exploration_endpoints(seeded):
    """OpenAPI must document every FASE 24 path (anti-drift contract)."""
    app, _ = seeded
    paths = _tc(app).get("/openapi.json").json()["paths"]
    expected = {
        "/v1/matches/{external_id}",
        "/v1/seasons/{season_code}/players/{player_external_id}",
        "/v1/seasons/{season_code}/teams/{team_external_id}",
        "/v1/players/search",
        "/v1/teams/search",
        "/v1/matches/search",
    }
    assert expected <= set(paths)
    # all are read-only GET endpoints
    for path in expected:
        assert paths[path]["get"], path


def test_openapi_documents_exploration_contract(seeded):
    """Pydantic-backed responses are reflected in the OpenAPI schema."""
    app, _ = seeded
    schemas = _tc(app).get("/openapi.json").json()["components"]["schemas"]
    assert schemas["PlayerProfileResponse"]["properties"]["teams"]["type"] == "array"
    assert schemas["TeamProfileResponse"]["properties"]["evolution"]["type"] == "array"
    assert schemas["MatchSearchResponse"]["properties"]["season_code"] is not None