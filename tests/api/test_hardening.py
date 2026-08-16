"""FASE 23.6 — API hardening tests.

Covers the production-readiness contract established by the phase:
parameter validation matrix, HTTP status semantics, determinism, resource
protection, leaderboard global ranking under limit, no secret leakage (response
AND logs), request correlation, health/readiness under failure, and the
generated OpenAPI surface of the six analytics endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
from feb_score.api.gateway import Readiness
from feb_score.api.main import create_app
from feb_score.domain.statistics.model import (
    PlayerLeaderboardMetric,
    PlayerStats,
    TeamLeaderboardMetric,
    TeamStats,
)
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway

SEASON = "2025-2026"

_SECRET_SNIPPETS = ("postgresql://", "dsn", "password", "secret", "Bearer ", "feb-key", "token")


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


def _seed(repo) -> None:
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
    repo.save_team_stats("M1", SEASON, [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    repo.save_team_stats("M2", SEASON, [_ts("T1", 75, 90), _ts("T2", 90, 75)])


@pytest.fixture
def api(db_path):
    """A seeded analytics app with a recording logger (to assert on logs)."""
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger())
    _seed(gateway._stats_repo)
    logger = RecordingLogger()
    auth = ApiKeyAuthenticationProvider({"secret-key": Principal(id="api", role="system")})
    app = create_app(gateway, logger=logger, auth=auth)
    return TestClient(app), gateway, logger


def _tc(api):
    return api[0]


def _gw(api):
    return api[1]


def _log(api):
    return api[2]


# ===========================================================================
# Input validation — season_code
# ===========================================================================

def test_season_code_empty_segment_is_controlled(api):
    # An empty path segment cannot match the route; Starlette 404s, which the
    # global handler maps to the stable envelope (never a 500).
    resp = _tc(api).get(f"/v1/seasons//players")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "HTTP_ERROR"


@pytest.mark.parametrize("bad", ["abc", "2025", "20-25", "25-26", "2025-2026x"])
def test_season_code_invalid_format_400(api, bad):
    resp = _tc(api).get(f"/v1/seasons/{bad}/players")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_season_code_too_long_400(api):
    resp = _tc(api).get(f"/v1/seasons/{'2025-2026' + '-' * 100}/players")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


@pytest.mark.parametrize("bad", ["2025_2026", "2025 2026", "２０２５"])
def test_season_code_unexpected_chars_400(api, bad):
    resp = _tc(api).get(f"/v1/seasons/{bad}/players")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


# ===========================================================================
# Input validation — limit
# ===========================================================================

@pytest.mark.parametrize("bad", ["0", "-1", "501", "999999999"])
def test_limit_out_of_range_400(api, bad):
    resp = _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": bad})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


@pytest.mark.parametrize("bad", ["abc", "1.5", "10e2"])
def test_limit_non_numeric_is_400_not_500(api, bad):
    resp = _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": bad})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_BODY"


def test_limit_absent_returns_full_season(api):
    body = _tc(api).get(f"/v1/seasons/{SEASON}/players").json()
    assert body["count"] == 4  # full, deterministic roster


def test_limit_upper_bound_accepted(api):
    assert _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": 500}).status_code == 200


# ===========================================================================
# Input validation — metric
# ===========================================================================

@pytest.mark.parametrize("metric", ["", "points ", "Points", "ppg", "classification"])
def test_unknown_player_metric_400(api, metric):
    resp = _tc(api).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": metric}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


def test_unknown_team_metric_400(api):
    resp = _tc(api).get(
        f"/v1/seasons/{SEASON}/teams/leaderboards", params={"metric": "bogus"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMETER"


# ===========================================================================
# Determinism
# ===========================================================================

_ENDPOINTS = [
    f"/v1/seasons/{SEASON}/players",
    f"/v1/seasons/{SEASON}/players/leaderboards?metric=points",
    f"/v1/seasons/{SEASON}/players/metrics",
    f"/v1/seasons/{SEASON}/teams",
    f"/v1/seasons/{SEASON}/teams/leaderboards?metric=classification",
    f"/v1/seasons/{SEASON}/teams/metrics",
]


def test_two_identical_requests_return_identical_bodies(api):
    for path in _ENDPOINTS:
        first = _tc(api).get(path).json()
        second = _tc(api).get(path).json()
        assert first == second, path


def test_leaderboard_global_ranking_preserved_under_limit(api):
    full = _tc(api).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points"}
    ).json()
    top = _tc(api).get(
        f"/v1/seasons/{SEASON}/players/leaderboards", params={"metric": "points", "limit": 2}
    ).json()
    assert [e["rank"] for e in top["items"]] == [1, 2]  # global positions, not renumbered
    assert [e["player_external_id"] for e in top["items"]] == [e["player_external_id"] for e in full["items"][:2]]


def test_limit_does_not_duplicate_or_reorder(api):
    a = _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": 2}).json()
    b = _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": 2}).json()
    assert a == b
    ids = [i["player_external_id"] for i in a["items"]]
    assert len(ids) == len(set(ids))


# ===========================================================================
# Pagination (limit only — offset deliberately not implemented)
# ===========================================================================

def test_unsupported_offset_param_is_ignored_and_result_is_stable(api):
    """No offset strategy exists (documented in FASE 23.6): an unsupported
    ``offset`` query param is ignored and the response is identical."""
    plain = _tc(api).get(f"/v1/seasons/{SEASON}/players", params={"limit": 2}).json()
    with_offset = _tc(api).get(
        f"/v1/seasons/{SEASON}/players", params={"limit": 2, "offset": 100}
    ).json()
    assert plain == with_offset


# ===========================================================================
# Security — no secret leakage (responses)
# ===========================================================================

def test_internal_error_never_leaks_secrets(api):
    gateway = _gw(api)

    def boom(season_code, limit=None):
        raise RuntimeError(
            "connect failed: postgresql://user:sup3rsecret@host:5432/feb?sslmode=require "
            "token=feb-token-12345"
        )

    original = gateway.list_season_player_aggregates
    gateway.list_season_player_aggregates = boom
    try:
        resp = TestClient(_tc(api).app, raise_server_exceptions=False).get(
            f"/v1/seasons/{SEASON}/players"
        )
    finally:
        gateway.list_season_player_aggregates = original

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
    payload = str(resp.json())
    assert all(snippet not in payload for snippet in ("postgresql://", "sup3rsecret", "feb-token-12345"))


# ===========================================================================
# Security — logging never contains credentials
# ===========================================================================

def test_authorization_header_never_appears_in_logs(api):
    key = "supersecret-api-key-xyz"
    _tc(api).get(
        f"/v1/seasons/{SEASON}/players",
        headers={"Authorization": f"Bearer {key}", "X-API-Key": key},
    )
    serialized = "\n".join(
        f"{level} {msg} {fields}" for level, msg, fields in _log(api).records
    )
    assert key not in serialized
    assert "Authorization" not in serialized


def test_request_log_records_are_structured_and_safe(api):
    resp = _tc(api).get(f"/v1/seasons/{SEASON}/players")
    request_logs = [r for r in _log(api).records if r[1] == "http_request"]
    assert request_logs
    fields = request_logs[-1][2]
    assert fields["method"] == "GET"
    assert fields["path"] == f"/v1/seasons/{SEASON}/players"
    assert fields["status"] == 200
    assert "duration_ms" in fields
    assert fields["request_id"] == resp.headers["x-request-id"]
    assert not any(k in fields for k in ("headers", "authorization", "body"))


def test_x_request_id_echoed_and_generated(api):
    echoed = _tc(api).get(
        f"/v1/seasons/{SEASON}/players", headers={"X-Request-ID": "trace-42"}
    )
    assert echoed.headers["x-request-id"] == "trace-42"
    generated = _tc(api).get(f"/v1/seasons/{SEASON}/players")
    assert generated.headers["x-request-id"]
    assert generated.headers["x-request-id"] != "trace-42"


# ===========================================================================
# Health / readiness
# ===========================================================================

def test_health_ok(api):
    resp = _tc(api).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_ok_with_checks(api):
    resp = _tc(api).get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["migrations"] == "up_to_date"
    assert all(snippet not in str(body) for snippet in ("postgresql://", "dsn", "password"))


def test_ready_reports_not_ready_without_stack_or_dsn(api):
    gateway = _gw(api)
    original = gateway.readiness
    gateway.readiness = lambda: Readiness(
        ready=False,
        checks={"database": "error: OperationalError (postgresql://user:pw@railway/x)"},
    )
    try:
        resp = _tc(api).get("/ready")
    finally:
        gateway.readiness = original
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "NOT_READY"
    assert "Traceback" not in str(body)


def test_ready_catastrophic_failure_is_500_generic(api):
    gateway = _gw(api)
    original = gateway.readiness

    def crash():
        raise RuntimeError("postgresql://railway:feb-secret@postgres.railway.internal/x")

    gateway.readiness = crash
    try:
        resp = TestClient(_tc(api).app, raise_server_exceptions=False).get("/ready")
    finally:
        gateway.readiness = original
    assert resp.status_code == 500
    payload = str(resp.json())
    assert "postgresql://" not in payload and "feb-secret" not in payload


# ===========================================================================
# OpenAPI
# ===========================================================================

_ANALYTICS_PATHS = [
    "/v1/seasons/{season_code}/players",
    "/v1/seasons/{season_code}/players/leaderboards",
    "/v1/seasons/{season_code}/players/metrics",
    "/v1/seasons/{season_code}/teams",
    "/v1/seasons/{season_code}/teams/leaderboards",
    "/v1/seasons/{season_code}/teams/metrics",
]


def test_openapi_exposes_all_six_analytics_endpoints(api):
    spec = _tc(api).get("/openapi.json").json()
    for path in _ANALYTICS_PATHS:
        assert path in spec["paths"], path
        op = spec["paths"][path]["get"]
        assert op["tags"] == ["analytics"]
        ref = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert ref["$ref"].startswith("#/components/schemas/SeasonResponse_")


def _query_param(spec, path, name):
    return next(
        p
        for p in spec["paths"][path]["get"]["parameters"]
        if p["name"] == name
    )


def test_openapi_documents_allowed_metric_values(api):
    spec = _tc(api).get("/openapi.json").json()
    player_metric = _query_param(spec, "/v1/seasons/{season_code}/players/leaderboards", "metric")
    team_metric = _query_param(spec, "/v1/seasons/{season_code}/teams/leaderboards", "metric")
    assert player_metric["schema"]["enum"] == list(PlayerLeaderboardMetric.ALL)
    assert team_metric["schema"]["enum"] == list(TeamLeaderboardMetric.ALL)


def test_openapi_contains_no_secret_models(api):
    """No OpenAPI schema property may look like a credential. ``CommandRequest``
    is a legitimate public command envelope; the check focuses on secrets."""
    spec = _tc(api).get("/openapi.json").json()
    for name, schema in spec["components"]["schemas"].items():
        for prop in schema.get("properties", {}):
            assert not any(
                snippet in prop.lower()
                for snippet in ("password", "secret", "token", "api_key", "dsn", "authorization")
            ), f"{name}.{prop}"