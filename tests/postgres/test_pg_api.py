"""FASE 12 — HTTP API over the PostgreSQL backend.

Re-runs the FASE 11 public API contract (create/finalize/read/ready/health) with
a PgGateway; anything the HTTP layer promised for SQLite must hold for Postgres.
"""

from uuid import uuid4

AUTH = {"Authorization": "Bearer system-key"}


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


def _command(payload, command_id=None):
    # FASE 13: no client-declared actor; identity comes from the API key.
    return {
        "command_id": command_id or str(uuid4()),
        "payload": payload,
    }


def test_pg_create_match_ok(pg_client):
    res = pg_client.post("/v1/commands/create_or_update_match", json=_command(_payload()), headers=AUTH)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["command_id"]
    assert [e["event_type"] for e in data["events"]] == ["match_upserted"]


def test_pg_finalize_ok(pg_client, pg_db):
    from feb_score.infrastructure.persistence.postgres.repositories import PgMatchRepository

    from sqlite_helpers import ready_to_finalize

    PgMatchRepository(pg_db).save(ready_to_finalize())
    fin = _command({"match_external_id": "2513600"})
    res = pg_client.post("/v1/commands/finalize_match", json=fin, headers=AUTH)
    assert res.status_code == 200, res.text
    assert any(e["event_type"] == "match_validated" for e in res.json()["events"])
    match = pg_client.get("/v1/matches/2513600").json()
    assert match["status"] == "FINALIZED"
    assert match["version"] == 2


def test_pg_read_match_dto(pg_client):
    pg_client.post("/v1/commands/create_or_update_match", json=_command(_payload()), headers=AUTH)
    res = pg_client.get("/v1/matches/2513600")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "SCHEDULED"
    assert body["home_team_id"] == "team-home"


def test_pg_ready_endpoint(pg_client):
    res = pg_client.get("/ready")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert "schema_version" in body["checks"]


def test_pg_health_endpoint(pg_client):
    res = pg_client.get("/health")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"


def test_pg_replayed_command_id_produces_no_duplicates(pg_client):
    cid = str(uuid4())
    first = pg_client.post("/v1/commands/create_or_update_match", json=_command(_payload(), cid), headers=AUTH)
    assert first.status_code == 200
    replay = pg_client.post("/v1/commands/create_or_update_match", json=_command(_payload(), cid), headers=AUTH)
    assert replay.status_code == 200
    assert replay.json()["events"] == []
    res = pg_client.get("/v1/matches/2513600")
    assert res.status_code == 200


def test_pg_readiness_down_via_api(pg_dsn):
    from fastapi.testclient import TestClient

    from feb_score.api.main import create_app
    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
    from feb_score.infrastructure.wiring import PgGateway

    db = PgDatabase("postgresql://postgres@127.0.0.1:1/nope")
    client = TestClient(create_app(PgGateway(db, logger=None)))
    res = client.get("/ready")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "NOT_READY"