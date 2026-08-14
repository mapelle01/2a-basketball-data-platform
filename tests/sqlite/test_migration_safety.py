"""FASE 10 — Migration safety: monotonic versions, one-time idempotent apply,
atomic partial-failure recovery, and automatic backup before destructive upgrades."""

import os
import sqlite3

import pytest

from feb_score.infrastructure.persistence import connection
from feb_score.infrastructure.persistence.connection import Migration, SqliteDatabase


def test_fresh_database_reaches_latest_version(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    assert db.user_version == max(m.version for m in connection.MIGRATIONS)
    conn = db.connect()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"matches", "players", "domain_events", "idempotency"} <= tables


def test_migrate_is_idempotent(sqlite_db):
    version = sqlite_db.user_version
    sqlite_db.migrate()
    assert sqlite_db.user_version == version


def test_versions_must_be_strictly_monotonic(db_path, monkeypatch):
    bogus = [
        Migration(2, "second", False, "SELECT 1;"),
        Migration(1, "first", False, "SELECT 1;"),
    ]
    monkeypatch.setattr(connection, "MIGRATIONS", bogus)
    with pytest.raises(ValueError):
        SqliteDatabase(db_path).migrate()


def test_partial_failure_rolls_back_and_retry_succeeds(db_path, monkeypatch):
    original = list(connection.MIGRATIONS)
    breaking = Migration(99, "boom", False, "CREATE TABLE broken (id INTEGER;")
    monkeypatch.setattr(connection, "MIGRATIONS", original + [breaking])

    db = SqliteDatabase(db_path)
    with pytest.raises(sqlite3.Error):
        db.migrate()
    # user_version reflects the last fully-applied migration, not the failed one.
    assert db.user_version == original[-1].version

    monkeypatch.setattr(connection, "MIGRATIONS", original)
    db.migrate()
    assert db.user_version == original[-1].version


def test_destructive_migration_backs_up_before_applying_and_can_roll_back(db_path, monkeypatch):
    db = SqliteDatabase(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO players (player_id, external_id, name, data) VALUES ('p1', 'pl-x', 'X', '{}')"
        )
    finally:
        conn.close()

    original = list(connection.MIGRATIONS)
    destructive = Migration(99, "drop_players", True, "DROP TABLE players;")
    monkeypatch.setattr(connection, "MIGRATIONS", original + [destructive])

    db.migrate()
    assert db.user_version == 99
    backup_path = f"{db_path}.pre-migrate-99.sqlite3"
    assert os.path.exists(backup_path)

    # Roll back the destructive upgrade from the automatic safety backup.
    fresh = SqliteDatabase(db_path)
    fresh.restore(backup_path)
    conn = fresh.connect()
    try:
        row = conn.execute("SELECT name FROM players WHERE external_id = 'pl-x'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["name"] == "X"


def test_upgrade_in_place_preserves_existing_data(db_path, monkeypatch):
    """A real v1 -> v2 upgrade (matches gains version column + CHECKs) keeps rows."""
    from feb_score.infrastructure.persistence import connection as conn_mod

    v1_migrations = [m for m in connection.MIGRATIONS if m.version <= 1]
    monkeypatch.setattr(conn_mod, "MIGRATIONS", v1_migrations)

    v1_db = SqliteDatabase(db_path)
    v1_db.migrate()  # v1 schema: matches has NO version column
    assert v1_db.user_version == 1
    conn = v1_db.connect()
    try:
        conn.execute(
            "INSERT INTO matches (match_id, external_id, competition_id, season_code, status, data)"
            " VALUES ('m1', 'old-1', 'c', '2025-2026', 'SCHEDULED',"
            " '{\"external_id\":\"old-1\",\"version\":1,\"home_team_id\":\"h\",\"away_team_id\":\"a\"}')"
        )
    finally:
        conn.close()

    monkeypatch.undo()
    upgraded = SqliteDatabase(db_path)
    upgraded.migrate()  # v2 applies: rebuild + version backfill
    assert upgraded.user_version == max(m.version for m in connection.MIGRATIONS)
    conn = upgraded.connect()
    try:
        row = conn.execute("SELECT external_id, version, status FROM matches WHERE external_id = 'old-1'").fetchone()
    finally:
        conn.close()
    assert row["external_id"] == "old-1"
    assert int(row["version"]) == 1
    assert row["status"] == "SCHEDULED"