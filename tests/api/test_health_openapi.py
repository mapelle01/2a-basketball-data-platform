"""FASE 11 — Health / readiness and OpenAPI availability."""

from fastapi.testclient import TestClient

from feb_score.api.gateway import Readiness
from feb_score.api.main import create_app
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_ok_and_checks_sqlite(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert int(body["checks"]["schema_version"]) >= 1


class _NotReadyGateway(SqliteGateway):
    def readiness(self):
        return Readiness(ready=False, checks={"database": "error: OperationalError"})


def test_ready_reports_503_when_dependency_down(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    app = create_app(_NotReadyGateway(db, logger=RecordingLogger()), logger=RecordingLogger())
    resp = TestClient(app).get("/ready")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "NOT_READY"
    assert resp.json()["error"]["details"]["database"].startswith("error")


def test_openapi_schema_is_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec["paths"]
    assert "/v1/commands/{command_type}" in paths
    assert "/v1/matches/{external_id}" in paths
    assert "/v1/contracts/{command_type}" in paths
    assert "/health" in paths and "/ready" in paths
    assert spec["info"]["version"].startswith("1.")


def test_docs_page_available(client):
    assert client.get("/docs").status_code == 200


def test_docs_and_openapi_disabled_when_env_true(db_path):
    import os

    from api_helpers import make_client

    os.environ["FEB_SCORE_DISABLE_DOCS"] = "true"
    try:
        app = make_client(db_path).app
        authed = TestClient(app)
        assert authed.get("/docs").status_code == 404
        assert authed.get("/openapi.json").status_code == 404
    finally:
        del os.environ["FEB_SCORE_DISABLE_DOCS"]


def test_docs_remain_enabled_by_default(db_path):
    import api_helpers

    app = api_helpers.make_client(db_path).app
    authed = TestClient(app)
    assert authed.get("/docs").status_code == 200
    assert authed.get("/openapi.json").status_code == 200


def test_contract_endpoint_serves_the_versioned_schema(client):
    resp = client.get("/v1/contracts/create_or_update_match")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["title"] == "CreateOrUpdateMatch Command v1"
    assert "command_id" in schema["required"]
    assert client.get("/v1/contracts/nope").status_code == 404


def test_request_id_is_generated_and_echoed(client):
    resp = client.get("/health")
    request_id = resp.headers.get("x-request-id")
    assert request_id and len(request_id) > 20

    resp2 = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert resp2.headers["x-request-id"] == "trace-123"