"""FASE 12 — PostgreSQL-specific: connection lifecycle, schema migrations and isolation."""

import pytest

from feb_score.infrastructure.persistence.postgres.connection import (
    PgDatabase,
    MIGRATIONS,
)
from feb_score.infrastructure.persistence.postgres.errors import translate_pg_error


def test_pg_connect_and_dsn(pg_dsn):
    db = PgDatabase(pg_dsn)
    conn = db.connect()
    assert conn.autocommit is True  # standalone semantics
    assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
    conn.close()


def test_pg_connect_txn_is_not_autocommit(pg_dsn):
    db = PgDatabase(pg_dsn)
    conn = db.connect_txn()
    assert conn.autocommit is False
    conn.close()


def test_migrations_create_schema_version(pg_db):
    assert pg_db.schema_version() == len(MIGRATIONS)


def test_migrations_are_idempotent(pg_db):
    pg_db.migrate()  # re-run
    pg_db.migrate()  # and again
    assert pg_db.schema_version() == len(MIGRATIONS)


def test_tables_created(pg_db):
    conn = pg_db.connect()
    tables = {
        r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (pg_db.schema,)
        ).fetchall()
    }
    expected = {"matches", "players", "teams", "competitions", "correction_proposals",
                "standing_snapshots", "leaderboards", "ratings", "publications",
                "idempotency", "domain_events", "schema_version"}
    assert expected <= tables
    conn.close()


def test_pg_schemas_are_isolated(pg_dsn):
    import uuid as _uuid

    db1 = PgDatabase(pg_dsn, schema=f"s_{_uuid.uuid4().hex[:8]}")
    db1.migrate()
    db2 = PgDatabase(pg_dsn, schema=f"s_{_uuid.uuid4().hex[:8]}")
    db2.migrate()
    try:
        assert db1.schema != db2.schema
        conn = db1.connect()
        conn.execute(
            "INSERT INTO matches (match_id, external_id, competition_id, season_code, status, version, data)"
            " VALUES ('m-1', 'x', 'c', 's', 'SCHEDULED', 1, '{}'::jsonb)"
        )
        conn.close()
        other = db2.connect()
        count = other.execute(
            "SELECT count(*) AS n FROM matches WHERE external_id = 'x'").fetchone()["n"]
        assert count == 0  # schema isolation: write to db1 invisible to db2
        other.close()
    finally:
        for db in (db1, db2):
            c = db.connect()
            c.execute(f"DROP SCHEMA IF EXISTS {db.schema} CASCADE")
            c.close()


def test_translate_pg_error_serialization():
    from psycopg.errors import SerializationFailure, DeadlockDetected, UniqueViolation, OperationalError

    from feb_score.infrastructure.persistence.errors import (
        ConstraintViolationError,
        DatabaseUnavailableError,
        DeadlockError,
        InfrastructureError,
        SerializationConflictError,
    )

    err = SerializationFailure("could not serialize access")
    assert isinstance(translate_pg_error(err), SerializationConflictError)

    assert isinstance(translate_pg_error(DeadlockDetected("deadlock")), DeadlockError)
    assert isinstance(translate_pg_error(UniqueViolation("dup")), ConstraintViolationError)
    assert isinstance(translate_pg_error(OperationalError("connection reset")), DatabaseUnavailableError)


def test_translate_pg_error_infrastructure_passthrough():
    from feb_score.infrastructure.persistence.errors import InfrastructureError

    exc = InfrastructureError("already classified")
    assert translate_pg_error(exc) is exc
    assert isinstance(translate_pg_error(RuntimeError("unknown")), InfrastructureError)