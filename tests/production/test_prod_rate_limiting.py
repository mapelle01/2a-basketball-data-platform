"""FASE 13 — Rate limiting: fixed-window, per-principal, 429 + Retry-After."""

from fastapi.testclient import TestClient

from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
from feb_score.api.main import create_app
from feb_score.api.middleware import RateLimiter
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway


def _client(db_path, limit=3):
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger())
    auth = ApiKeyAuthenticationProvider(
        {"sys-key": Principal(id="api", role="system"), "ed-key": Principal(id="editor-1", role="editor")}
    )
    app = create_app(
        gateway,
        logger=RecordingLogger(),
        auth=auth,
        rate_limiter=RateLimiter(limit=limit, window_seconds=60),
    )
    return TestClient(app)


def _payload():
    return {
        "external_id": "2513600",
        "competition_id": "feb-comp",
        "season_code": "2025-2026",
        "round_number": 5,
        "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }


def test_commands_over_the_limit_return_429(db_path):
    client = _client(db_path, limit=2)
    headers = {"Authorization": "Bearer sys-key"}
    url = "/v1/commands/create_or_update_match"
    body = {"payload": _payload()}
    assert client.post(url, json=body, headers=headers).status_code == 200
    assert client.post(url, json=body, headers=headers).status_code == 200
    limited = client.post(url, json=body, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.headers.get("retry-after")
    # The limit is per principal: another key is not affected.
    assert client.post(url, json=body, headers={"Authorization": "Bearer ed-key"}).status_code == 200


def test_anonymous_requests_are_also_limited_by_ip(db_path):
    client = _client(db_path, limit=1)
    url = "/v1/commands/create_or_update_match"
    # Anonymous commands would be 401, but the limiter still counts them first.
    assert client.post(url, json={"payload": _payload()}).status_code == 401
    limited = client.post(url, json={"payload": _payload()})
    assert limited.status_code == 429


def test_reads_and_health_are_not_rate_limited(db_path):
    client = _client(db_path, limit=2)
    url = "/v1/commands/create_or_update_match"
    body = {"payload": _payload()}
    assert client.post(url, json=body, headers={"Authorization": "Bearer sys-key"}).status_code == 200
    assert client.post(url, json=body, headers={"Authorization": "Bearer sys-key"}).status_code == 200
    # Limiter exhausted for this principal, but reads stay available.
    for _ in range(5):
        assert client.get("/v1/matches/2513600").status_code == 200
        assert client.get("/health").status_code == 200


def test_rate_limit_disabled_means_no_429(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger())
    auth = ApiKeyAuthenticationProvider({"sys-key": Principal(id="api", role="system")})
    app = create_app(gateway, logger=RecordingLogger(), auth=auth, rate_limiter=None)
    client = TestClient(app)
    url = "/v1/commands/create_or_update_match"
    body = {"payload": _payload()}
    for _ in range(5):
        assert client.post(url, json=body, headers={"Authorization": "Bearer sys-key"}).status_code == 200