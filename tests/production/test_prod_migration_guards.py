"""FASE 13 — Migration guards: refuse a future/unknown schema (sqlite + pg).

A database whose schema_version is HIGHER than this binary supports must not be
silently skipped, downgraded or "completed": it was written by a NEWER version.
Both backends raise ``InfrastructureError`` instead of proceeding.
"""

import pytest

from feb_score.infrastructure.persistence.connection import MIGRATIONS as SQLITE_MIGRATIONS
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.errors import InfrastructureError
from feb_score.infrastructure.persistence.postgres.connection import MIGRATIONS as PG_MIGRATIONS


def test_sqlite_future_version_guard(tmp_path):
    db = SqliteDatabase(str(tmp_path / "feb.db"))
    db.migrate()
    expected = len(SQLITE_MIGRATIONS)
    assert db.user_version == expected

    # Simulate a database written by a NEWER binary.
    conn = db.connect()
    conn.execute(f"PRAGMA user_version = {expected + 100}")
    conn.close()

    with pytest.raises(InfrastructureError, match="newer than the supported maximum"):
        db.migrate()


def test_sqlite_idempotent_at_current_version(tmp_path):
    db = SqliteDatabase(str(tmp_path / "feb.db"))
    db.migrate()
    db.migrate()  # no-op, no error
    assert db.user_version == len(SQLITE_MIGRATIONS)


def test_pg_future_version_guard(pg_db):
    pg_db.migrate()
    expected = len(PG_MIGRATIONS)
    assert pg_db.schema_version() == expected

    conn = pg_db.connect()
    conn.execute(f"INSERT INTO schema_version (version, name) VALUES ({expected + 100}, 'future')")
    conn.close()

    with pytest.raises(InfrastructureError, match="newer than the supported maximum"):
        pg_db.migrate()


def test_pg_idempotent_at_current_version(pg_db):
    pg_db.migrate()
    pg_db.migrate()  # no-op, no error
    assert pg_db.schema_version() == len(PG_MIGRATIONS)


def test_pg_apply_migration_rolls_back_on_failure(pg_db):
    """FASE 15 §3 — a failing migration rolls back atomically: the partially
    executed statements are undone and the version is NOT recorded, so a retry
    starts clean (fail-closed, reproducible from scratch or in place)."""
    from feb_score.infrastructure.persistence.postgres.connection import (
        PgMigration,
    )

    pg_db.migrate()  # schema_version table + version 1 in place
    conn = pg_db.connect_txn()  # autocommit=False: first statement opens a txn
    try:
        # First statement succeeds, second is invalid SQL -> whole migration must roll back.
        with pytest.raises(Exception, match="syntax error"):
            pg_db._apply_migration(
                conn,
                PgMigration(
                    version=2,
                    name="bad",
                    script="CREATE TABLE broken_table (id INT NOT NULL); THIS IS NOT SQL;",
                ),
            )
    finally:
        conn.close()

    # Rollback undid the first statement and version 2 was NOT recorded.
    check = pg_db.connect()
    try:
        assert check.execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables"
            " WHERE table_schema = %s AND table_name = 'broken_table'",
            (pg_db.schema,),
        ).fetchone()["n"] == 0
        version_row = check.execute(
            "SELECT COUNT(*) AS n FROM %s.schema_version WHERE version = 2"
            % pg_db.schema
        ).fetchone()
        assert version_row["n"] == 0
    finally:
        check.close()

    # A clean migrate() still succeeds and stays at the known version.
    pg_db.migrate()
    assert pg_db.schema_version() == len(PG_MIGRATIONS)