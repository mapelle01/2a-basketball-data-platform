"""FASE 11 — Persistence + restart + outbox semantics from HTTP.

Flow under test: HTTP -> CommandRunner -> SQLite -> restart -> HTTP GET -> correct
state. Also: events are persisted with outbox semantics and are NOT marked
delivered just because the API responded.
"""

from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from api_helpers import create_payload, ready_to_finalize


def test_create_persists_across_restart(client, client_factory, db_path):
    assert client.post("/v1/commands/create_or_update_match",
                       json={"payload": create_payload()}).status_code == 200

    restarted = client_factory(db_path)
    match = restarted.get("/v1/matches/2513600")
    assert match.status_code == 200
    assert match.json()["status"] == "SCHEDULED"


def test_finalize_flow_across_restart(client, client_factory, db_path):
    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    assert client.post("/v1/commands/finalize_match",
                       json={"payload": {"match_external_id": "2513600"}}).status_code == 200

    restarted = client_factory(db_path)
    match = restarted.get("/v1/matches/2513600")
    assert match.status_code == 200
    assert match.json()["status"] == "FINALIZED"
    assert match.json()["version"] == 2


def test_events_are_persisted_with_outbox_semantics(client, db_path):
    db = SqliteDatabase(db_path)
    assert client.post("/v1/commands/create_or_update_match",
                       json={"payload": create_payload()}).status_code == 200

    store = SqliteEventStore(db)
    pending = store.pending_count()
    assert pending == 1  # one event persisted, still undelivered

    conn = db.connect()
    try:
        delivered = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_events WHERE delivered = 1"
        ).fetchone()["n"]
    finally:
        conn.close()
    # The API response never marks events delivered: dispatch is a separate step.
    assert delivered == 0


def test_finalize_produces_outbox_events(client, db_path):
    db = SqliteDatabase(db_path)
    SqliteMatchRepository(db).save(ready_to_finalize())
    resp = client.post("/v1/commands/finalize_match",
                       json={"payload": {"match_external_id": "2513600"}})
    assert resp.status_code == 200
    event_types = [e["event_type"] for e in resp.json()["events"]]
    assert {"match_validation_started", "match_validated", "match_finalized"} <= set(event_types)
    assert SqliteEventStore(db).pending_count() == len(event_types)