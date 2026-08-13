"""FASE 12 — PostgreSQL-specific: readiness semantics and JSONB storage."""

from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    MatchStatus,
    SeasonCode,
)


def _create_match_payload():
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


def test_pg_readiness_ok(pg_gateway):
    readiness = pg_gateway.readiness()
    assert readiness.ready is True
    assert readiness.checks["database"] == "ok"
    assert "schema_version" in readiness.checks


def test_pg_readiness_down(pg_dsn):
    """A database outage must yield ready=False (never raise)."""
    import pytest
    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
    from feb_score.infrastructure.wiring import PgGateway

    db = PgDatabase(f"postgresql://postgres@127.0.0.1:1/nope")
    gateway = PgGateway(db, logger=None)
    readiness = gateway.readiness()
    assert readiness.ready is False
    assert readiness.checks["database"] != "ok"


def test_pg_jsonb_payload_is_jsonb(pg_db):
    from feb_score.domain.events import MatchUpserted
    from feb_score.domain.value_objects import EventMeta

    store = pg_db.event_store()
    event = MatchUpserted(
        event_id=str(uuid4()),
        meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
        source={"origin": "test"},
        payload={"external_id": "2513600", "nested": {"round": 5, "flags": [True, None]}},
    )
    store.append_many([event])

    conn = pg_db.connect()
    row = conn.execute(
        "SELECT payload, payload::text AS raw, jsonb_typeof(payload) AS t FROM domain_events WHERE event_id = %s",
        (event.event_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["t"] == "object"  # stored as JSONB, not text
    import json as _json

    raw = _json.loads(row["raw"])
    assert raw["payload"]["external_id"] == "2513600"
    assert raw["payload"]["nested"]["round"] == 5


def test_pg_match_jsonb_round_trip_special_values(pg_gateway):
    payload = _create_match_payload()
    result = pg_gateway.run(
        "create_or_update_match", command_id=str(uuid4()),
        actor={"id": "system", "role": "system"}, payload=payload,
    )
    assert len(result.events) == 1
    match = pg_gateway.get_match("2513600")
    assert match["status"] == "SCHEDULED"
    assert match["round_number"] == 5
    assert match["home_team_id"] == "team-home"
    assert match["season_code"] == "2025-2026"


def test_pg_matches_enforce_domain_checks(pg_db):
    """The matches table must enforce the same integrity SQLite's CHECK clauses do:
    known status and home <> away."""
    conn = pg_db.connect()
    base = "INSERT INTO matches (external_id, competition_id, season_code, round_number,"
    " status, scheduled_at, home_team_id, away_team_id, source, payload, version)"
    try:
        with pytest.raises(Exception):
            conn.execute(
                base + " VALUES ('bad-status', 'c', 's', 1, 'NOT_A_STATUS', NOW(), 'h', 'a',"
                " '{}'::jsonb, '{}'::jsonb, 1)"
            )
        with pytest.raises(Exception):
            conn.execute(
                base + " VALUES ('same-teams', 'c', 's', 1, 'SCHEDULED', NOW(), 'h', 'h',"
                " '{}'::jsonb, '{}'::jsonb, 1)"
            )
    finally:
        conn.close()