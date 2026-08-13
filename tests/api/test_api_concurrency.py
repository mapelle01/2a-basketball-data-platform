"""FASE 11 — Concurrency at the HTTP boundary.

* ``StaleVersionError`` is NEVER hidden: it maps to 409 CONFLICT.
* Under ``BEGIN IMMEDIATE`` concurrent writers are serialized, so two parallel
  HTTP finalizations both observe fresh state and neither is lost (invariant
  verified below).
"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from feb_score.api.main import create_app
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.errors import StaleVersionError
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository
from feb_score.infrastructure.wiring import SqliteGateway

from api_helpers import make_client, make_test_auth_provider, ready_to_finalize


class _StaleFinalizeGateway(SqliteGateway):
    def run(self, command_type, **kwargs):
        if command_type == "finalize_match":
            raise StaleVersionError("stale snapshot")
        return super().run(command_type, **kwargs)


def test_stale_version_conflict_maps_to_409(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = _StaleFinalizeGateway(db, logger=RecordingLogger())
    client = TestClient(create_app(gateway, logger=RecordingLogger(), auth=make_test_auth_provider()))
    resp = client.post("/v1/commands/finalize_match", json={"payload": {"match_external_id": "2513600"}},
                             headers={"Authorization": "Bearer system-key"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_parallel_finalizations_never_lose_updates(db_path):
    """Two concurrent HTTP finalizations on the same match: serialized by SQLite,
    the second observes the already-finalized state and cannot clobber the first
    write. One real finalize is applied (version 2), state stays consistent."""
    db = SqliteDatabase(db_path)
    db.migrate()
    SqliteMatchRepository(db).save(ready_to_finalize())
    client = make_client(db_path)

    def finalize(_):
        return client.post(
            "/v1/commands/finalize_match",
            json={"command_id": str(uuid4()), "payload": {"match_external_id": "2513600"}},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(finalize, range(2)))

    assert set(statuses) == {200}  # both completed; second became a validation-failed event
    match = client.get("/v1/matches/2513600").json()
    assert match["status"] == "FINALIZED"
    assert match["version"] == 2  # exactly one real finalize applied, no lost update
    assert match["score_summary"]["home_score"] == 80  # first write preserved intact

    conn = db.connect()
    try:
        finalized_events = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_events WHERE event_type = 'MatchFinalized'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert finalized_events == 1