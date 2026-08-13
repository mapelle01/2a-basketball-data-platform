"""FASE 11 — HTTP error mapping: stable envelope, distinct statuses, no leaks."""

import json
from uuid import uuid4

from feb_score.api.main import create_app
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.errors import InfrastructureError, StaleVersionError
from feb_score.infrastructure.wiring import SqliteGateway

from api_helpers import create_payload, make_client, ready_to_finalize, make_test_auth_provider


def test_malformed_json_returns_400(client):
    resp = client.post(
        "/v1/commands/create_or_update_match",
        content="{not valid json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "INVALID_BODY"
    assert "Traceback" not in resp.text


def test_contract_failure_returns_422(client):
    resp = client.post("/v1/commands/finalize_match", json={"payload": {"bad": "x"}})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "CONTRACT_VALIDATION"
    assert body["command_id"]


def test_unknown_command_returns_404(client):
    resp = client.post("/v1/commands/non_existent_command", json={"payload": {}})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "UNKNOWN_COMMAND"


def test_not_found_aggregate_returns_404(client):
    resp = client.post("/v1/commands/finalize_match", json={"payload": {"match_external_id": "missing"}})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_domain_error_returns_422_with_class_code(db_path):
    """A DomainError (other than EntityNotFound) maps to 422 with the error
    class code. Real handlers convert most domain rejections into events, so
    this path is exercised via an injected gateway (same technique as 409/503)."""
    from feb_score.domain.errors import InvalidCorrection
    from feb_score.infrastructure.persistence.connection import SqliteDatabase
    from fastapi.testclient import TestClient

    db = SqliteDatabase(db_path)
    db.migrate()
    app = create_app(_RaisingGateway(db, InvalidCorrection("bad change")), logger=RecordingLogger(), auth=make_test_auth_provider())
    resp = TestClient(app).post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600"}},
        headers={"Authorization": "Bearer system-key"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CORRECTION"
    assert resp.json()["error"]["message"] == "bad change"


class _RaisingGateway(SqliteGateway):
    def __init__(self, db, exc):
        super().__init__(db, logger=RecordingLogger())
        self._exc = exc

    def run(self, command_type, **kwargs):
        raise self._exc


def test_stale_version_maps_to_409(db_path):
    db = __import__("feb_score.infrastructure.persistence.connection", fromlist=["SqliteDatabase"]).SqliteDatabase(db_path)
    db.migrate()
    app = create_app(_RaisingGateway(db, StaleVersionError("stale")), logger=RecordingLogger(), auth=make_test_auth_provider())
    from fastapi.testclient import TestClient

    resp = TestClient(app).post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600"}},
        headers={"Authorization": "Bearer system-key"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"
    assert "concurrent" in resp.json()["error"]["message"]


def test_infrastructure_error_maps_to_503(db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase
    from fastapi.testclient import TestClient

    db = SqliteDatabase(db_path)
    db.migrate()
    app = create_app(_RaisingGateway(db, InfrastructureError("db busy")), logger=RecordingLogger(), auth=make_test_auth_provider())
    resp = TestClient(app).post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600"}},
        headers={"Authorization": "Bearer system-key"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "INFRASTRUCTURE_UNAVAILABLE"


def test_unexpected_error_returns_500_without_stack(db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase
    from fastapi.testclient import TestClient

    db = SqliteDatabase(db_path)
    db.migrate()
    app = create_app(_RaisingGateway(db, RuntimeError("boom")), logger=RecordingLogger(), auth=make_test_auth_provider())
    # ServerErrorMiddleware always re-raises server exceptions for logging;
    # the test client must not surface them so we can assert on the response.
    resp = TestClient(app, raise_server_exceptions=False).post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600"}},
        headers={"Authorization": "Bearer system-key"},
    )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "boom" not in resp.text
    assert "Traceback" not in resp.text


def test_envelope_unknown_field_returns_400(client):
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": create_payload(), "surprise": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_BODY"