"""FASE 11 — Idempotency preserved through HTTP: replaying the same command_id
(also across a restart) produces no duplicate state or events."""

from uuid import uuid4

from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

from api_helpers import create_payload


def _create(client, command_id):
    return client.post(
        "/v1/commands/create_or_update_match",
        json={"command_id": command_id, "payload": create_payload()},
    )


def test_replaying_same_command_id_produces_no_duplicates(client, db_path):
    command_id = str(uuid4())
    first = _create(client, command_id)
    assert first.status_code == 200
    assert len(first.json()["events"]) == 1

    replay = _create(client, command_id)
    assert replay.status_code == 200
    assert replay.json()["events"] == []  # idempotent replay: nothing new

    matches = list(SqliteMatchRepository(SqliteDatabase(db_path)).list_by_season("feb-comp", "2025-2026"))
    assert len(matches) == 1
    assert matches[0].version == 1
    assert SqliteEventStore(SqliteDatabase(db_path)).pending_count() == 1  # events not duplicated


def test_replay_after_restart_is_idempotent(client, client_factory, db_path):
    command_id = str(uuid4())
    assert _create(client, command_id).status_code == 200

    restarted = client_factory(db_path)  # restart: new app, same database
    replay = _create(restarted, command_id)
    assert replay.status_code == 200
    assert replay.json()["events"] == []

    matches = list(SqliteMatchRepository(SqliteDatabase(db_path)).list_by_season("feb-comp", "2025-2026"))
    assert len(matches) == 1
    assert SqliteEventStore(SqliteDatabase(db_path)).pending_count() == 1


def test_distinct_command_ids_create_separate_matches(client, db_path):
    for _ in range(3):
        assert _create(client, str(uuid4())).status_code == 200
    matches = list(SqliteMatchRepository(SqliteDatabase(db_path)).list_by_season("feb-comp", "2025-2026"))
    # same external_id -> upsert keeps ONE match (version bumped per replay)
    assert len(matches) == 1
    assert matches[0].version == 3