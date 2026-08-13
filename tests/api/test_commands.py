"""FASE 11 — HTTP command endpoints: happy paths through CommandRunner + SQLite."""

from datetime import datetime
from uuid import uuid4

from feb_score.domain.player.model import Player
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import ExternalId, PlayerId, TeamId
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteLeaderboardRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

from api_helpers import create_payload, ready_to_finalize


def test_create_match_ok(client):
    resp = client.post("/v1/commands/create_or_update_match", json={"payload": create_payload()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["command_id"]
    assert body["status"] == "accepted"
    event_types = [e["event_type"] for e in body["events"]]
    assert "match_upserted" in event_types

    match = client.get("/v1/matches/2513600")
    assert match.status_code == 200
    assert match.json()["status"] == "SCHEDULED"


def test_finalize_match_ok(client, db_path):
    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    resp = client.post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600", "validation_context": {"strict": True}}},
    )
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "match_validated" in types

    match = client.get("/v1/matches/2513600").json()
    assert match["status"] == "FINALIZED"
    assert match["version"] == 2
    assert match["score_summary"] == {"home_score": 80, "away_score": 77}


def test_propose_and_approve_correction_flow(client, db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase

    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    assert client.post("/v1/commands/finalize_match",
                       json={"payload": {"match_external_id": "2513600"}}).status_code == 200

    proposal_id = str(uuid4())
    propose = client.post("/v1/commands/propose_correction", json={"command_id": proposal_id, "payload": {
        "match_external_id": "2513600",
        "proposed_by": {"id": "editor-1", "role": "editor"},
        "reason": "official score",
        "changes": [{"op": "update_score", "home_score": 80, "away_score": 77}],
    }})
    assert propose.status_code == 200
    assert propose.json()["events"][0]["event_type"] == "correction_proposed"

    approve = client.as_role("admin").post("/v1/commands/approve_correction", json={
        "payload": {
            "proposal_id": proposal_id,
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": "2026-02-02T12:00:00Z",
        },
    })
    assert approve.status_code == 200

    proposal = client.get(f"/v1/correction-proposals/{proposal_id}")
    assert proposal.status_code == 200
    assert proposal.json()["status"] == "APPROVED"
    match = client.get("/v1/matches/2513600").json()
    assert match["version"] == 3
    assert match["correction_history_count"] == 1


def test_register_player_to_squad_ok(client, db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase

    db = SqliteDatabase(db_path)
    SqlitePlayerRepository(db).save(Player(external_id=ExternalId("pl-987"), player_id=PlayerId(str(uuid4())), name="Juan"))
    SqliteTeamRepository(db).save(Team(external_id=ExternalId("team-123"), team_id=TeamId(str(uuid4())), name="Club"))

    resp = client.as_role("admin").post("/v1/commands/register_player_to_squad", json={
        "payload": {
            "player_external_id": "pl-987", "team_external_id": "team-123",
            "season_code": "2025-2026", "registered_from": "2025-08-01T00:00:00Z",
        },
    })
    assert resp.status_code == 200
    assert resp.json()["events"][0]["event_type"] == "player_registered"
    assert client.get("/v1/players/pl-987").json()["registrations_count"] == 1
    assert client.get("/v1/teams/team-123").json()["registrations_count"] == 1


def test_compute_player_rating_ok(client, db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase

    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    resp = client.post("/v1/commands/compute_player_rating", json={"payload": {
        "player_external_id": "pl-1", "season_code": "2025-2026",
        "rating_version": "v1.0", "competition_id": "feb-comp",
    }})
    assert resp.status_code == 200
    assert resp.json()["events"][0]["event_type"] == "player_rating_computed"


def test_generate_leaderboard_ok_and_readable(client, db_path):
    from feb_score.infrastructure.persistence.connection import SqliteDatabase

    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    assert client.post("/v1/commands/finalize_match",
                       json={"payload": {"match_external_id": "2513600"}}).status_code == 200
    resp = client.post("/v1/commands/generate_leaderboard", json={"payload": {
        "season_code": "2025-2026", "category": "points_per_game",
        "min_games": 0, "top_n": 10, "competition_id": "feb-comp",
    }})
    assert resp.status_code == 200
    assert resp.json()["events"][0]["event_type"] == "leaderboard_generated"

    leaderboard_id = str(SqliteLeaderboardRepository(SqliteDatabase(db_path)).list_all()[0].leaderboard_id)
    board = client.get(f"/v1/leaderboards/{leaderboard_id}")
    assert board.status_code == 200
    assert board.json()["category"] == "points_per_game"
    assert board.json()["entries"][0]["player_external_id"] == "pl-1"


def test_backfill_season_ok(client):
    resp = client.as_role("admin").post("/v1/commands/backfill_season", json={
        "payload": {"season_code": "2025-2026"},
    })
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "season_backfill_started" in types
    assert "season_backfill_completed" in types


def test_command_id_is_echoed(client):
    command_id = str(uuid4())
    resp = client.post("/v1/commands/create_or_update_match",
                       json={"command_id": command_id, "payload": create_payload()})
    assert resp.status_code == 200
    assert resp.json()["command_id"] == command_id


def test_generated_command_id_when_absent(client):
    resp = client.post("/v1/commands/create_or_update_match", json={"payload": create_payload()})
    assert resp.status_code == 200
    assert len(resp.json()["command_id"]) > 20  # a uuid4 was generated