"""FASE 13 — Graceful shutdown and the production composition root.

feb_score keeps no background workers and no connection pool, so shutdown is
inherently safe: in-flight requests finish (Uvicorn), transactions commit/rollback
in their UoW context, and every connection is closed in a ``finally``. These tests
make that observable: startup/shutdown are logged and the database stays usable
(no leaked locks/connections).
"""

import pytest
from fastapi.testclient import TestClient

from feb_score.infrastructure.config import Settings
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase


def test_lifespan_startup_and_shutdown_are_logged(db_path):
    from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
    from feb_score.api.main import create_app
    from feb_score.infrastructure.wiring import SqliteGateway

    logger = RecordingLogger()
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=logger)
    auth = ApiKeyAuthenticationProvider({"sys-key": Principal(id="api", role="system")})
    app = create_app(gateway, logger=logger, auth=auth)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert any(r[1] == "app_startup" for r in logger.records)

    assert any(r[1] == "app_shutdown" for r in logger.records)


def test_database_usable_after_app_shutdown(db_path):
    from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
    from feb_score.api.main import create_app
    from feb_score.infrastructure.wiring import SqliteGateway

    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=None)
    auth = ApiKeyAuthenticationProvider({"sys-key": Principal(id="api", role="system")})
    app = create_app(gateway, logger=None, auth=auth)

    with TestClient(app) as client:
        client.post(
            "/v1/commands/create_or_update_match",
            json={"payload": {
                "external_id": "2513600", "competition_id": "feb-comp",
                "season_code": "2025-2026", "round_number": 5,
                "scheduled_at": "2026-02-01T18:30:00Z",
                "home_team": {"external_id": "team-home", "name": "Home"},
                "away_team": {"external_id": "team-away", "name": "Away"},
                "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
            }},
            headers={"Authorization": "Bearer sys-key"},
        )

    # After shutdown: the database is not locked and the committed data is intact.
    conn = db.connect()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_build_production_app_assembles_and_serves(tmp_path, monkeypatch):
    from feb_score.server import build_production_app

    settings = Settings(
        env="test",
        db_path=str(tmp_path / "prod.db"),
        api_keys="sys-key=api:system",
        rate_limit_enabled=False,
    )
    app = build_production_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"]["migrations"] == "up_to_date"
        ok = client.post(
            "/v1/commands/create_or_update_match",
            json={"payload": {
                "external_id": "2513600", "competition_id": "feb-comp",
                "season_code": "2025-2026", "round_number": 5,
                "scheduled_at": "2026-02-01T18:30:00Z",
                "home_team": {"external_id": "team-home", "name": "Home"},
                "away_team": {"external_id": "team-away", "name": "Away"},
                "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
            }},
            headers={"Authorization": "Bearer sys-key"},
        )
        assert ok.status_code == 200


def test_build_production_app_uses_postgres_backend(pg_dsn, monkeypatch):
    import uuid

    from feb_score.server import build_production_app

    schema = f"boot_{uuid.uuid4().hex[:12]}"
    import psycopg

    conn = psycopg.connect(pg_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        conn.close()

    settings = Settings(
        env="test",
        database_url=f"{pg_dsn}?options=-csearch_path%3D{schema}",
        api_keys="sys-key=api:system",
        rate_limit_enabled=False,
        pg_connect_timeout_ms=3000,
    )
    app = build_production_app(settings)
    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"]["migrations"] == "up_to_date"

    conn = psycopg.connect(pg_dsn, autocommit=True)
    try:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()