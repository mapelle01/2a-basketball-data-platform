"""FASE 13 — Observability: request_id + command_id correlation, no secrets in logs."""

import pytest
from fastapi.testclient import TestClient

from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
from feb_score.api.main import create_app
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_dispatcher import (
    LoggingPublisher,
    SyncEventDispatcher,
)
from feb_score.infrastructure.wiring import SqliteGateway


def _app(db_path, logger):
    db = SqliteDatabase(db_path)
    db.migrate()
    dispatcher = SyncEventDispatcher(
        db, LoggingPublisher(logger=logger), logger=logger
    )
    gateway = SqliteGateway(db, dispatcher=dispatcher, logger=logger)
    auth = ApiKeyAuthenticationProvider({"sys-key": Principal(id="api", role="system")})
    return create_app(gateway, logger=logger, auth=auth)


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


def test_request_and_command_ids_correlate(db_path):
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    headers = {"Authorization": "Bearer sys-key"}
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": _payload()},
        headers=headers,
    )
    assert resp.status_code == 200
    request_id = resp.headers["x-request-id"]
    command_id = resp.json()["command_id"]

    # Every record for this request carries the same request_id...
    for level, message, fields in logger.records:
        if fields.get("request_id") is not None:
            assert fields["request_id"] == request_id, message
    # ...and the command lifecycle records carry the command_id.
    completed = [r for r in logger.records if r[1] == "command_completed"]
    assert len(completed) == 1
    assert completed[0][2]["command_id"] == command_id
    assert completed[0][2]["events"] == 1
    # An http_request summary record exists with status and duration.
    http = [r for r in logger.records if r[1] == "http_request"]
    assert http and http[0][2]["status"] == 200
    assert "duration_ms" in http[0][2]


def test_client_supplied_request_id_is_preserved(db_path):
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": _payload()},
        headers={"Authorization": "Bearer sys-key", "X-Request-ID": "trace-abc"},
    )
    assert resp.headers["x-request-id"] == "trace-abc"


def test_secrets_never_appear_in_logs(db_path):
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": _payload()},
        headers={"Authorization": "Bearer sys-key"},
    )
    for _, _, fields in logger.records:
        for key, value in fields.items():
            if isinstance(value, str):
                assert "sys-key" not in value, key
                assert db_path not in value, key


def test_failed_requests_are_logged_with_status(db_path):
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    client.post("/v1/commands/finalize_match", json={"payload": {"bad": "x"}},
                headers={"Authorization": "Bearer sys-key"})
    http = [r for r in logger.records if r[1] == "http_request"]
    assert http and http[0][2]["status"] == 422


def test_command_lifecycle_records_carry_request_id(db_path):
    """F-02: request_id propagates through the command lifecycle and event logs,
    correlating HTTP request -> command_id -> command logs -> event logs."""
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": _payload()},
        headers={"Authorization": "Bearer sys-key"},
    )
    assert resp.status_code == 200
    request_id = resp.headers["x-request-id"]

    for name in ("command_started", "command_completed", "dispatch_completed"):
        records = [r for r in logger.records if r[1] == name]
        assert records, name
        assert all(r[2].get("request_id") == request_id for r in records), name
    published = [r for r in logger.records if r[1] == "event_published"]
    assert published and all(r[2].get("request_id") == request_id for r in published)


def test_gateway_logs_its_backend(db_path):
    logger = RecordingLogger()
    client = TestClient(_app(db_path, logger))
    client.get("/health")
    boot = [r for r in logger.records if r[1] == "gateway_ready"]
    assert boot and boot[0][2]["backend"] == "sqlite"