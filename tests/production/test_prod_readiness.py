"""FASE 13 — Readiness distinctions: pending vs future/unknown vs up-to-date.

/health answers "is the process alive"; /ready answers "are the dependencies
healthy AND at the exact schema version we support". A gateway is ready only when
migrations are up-to-date.
"""

import pytest

from feb_score.infrastructure.persistence.connection import MIGRATIONS as SQLITE_MIGRATIONS
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway


def _gateway(db_path):
    return SqliteGateway(SqliteDatabase(db_path), logger=None)


def test_ready_when_migrated(tmp_path):
    path = str(tmp_path / "feb.db")
    db = SqliteDatabase(path)
    db.migrate()
    r = _gateway(path).readiness()
    assert r.ready is True
    assert r.checks["database"] == "ok"
    assert r.checks["migrations"] == "up_to_date"


def test_not_ready_when_migrations_pending(tmp_path):
    """A fresh (unmigrated) database: reachable but migrations are pending."""
    path = str(tmp_path / "feb.db")
    r = _gateway(path).readiness()
    assert r.ready is False
    assert r.checks["database"] == "ok"
    assert r.checks["migrations"].startswith("pending")


def test_not_ready_when_schema_is_future(tmp_path):
    path = str(tmp_path / "feb.db")
    db = SqliteDatabase(path)
    db.migrate()
    conn = db.connect()
    conn.execute(f"PRAGMA user_version = {len(SQLITE_MIGRATIONS) + 5}")
    conn.close()
    r = _gateway(path).readiness()
    assert r.ready is False
    assert r.checks["migrations"].startswith("future")


def test_not_ready_when_database_unreachable(tmp_path):
    # A database path that is actually a DIRECTORY cannot be opened: connect()
    # fails, and readiness reports the dependency as unhealthy.
    path = str(tmp_path / "feb.db")
    __import__("os").mkdir(path)
    r = _gateway(path).readiness()
    assert r.ready is False
    assert r.checks["database"].startswith("error")


def test_pg_ready_and_future_states(pg_db):
    from feb_score.infrastructure.wiring import PgGateway

    pg_db.migrate()
    gateway = PgGateway(pg_db, logger=None)
    assert gateway.readiness().ready is True

    conn = pg_db.connect()
    conn.execute("INSERT INTO schema_version (version, name) VALUES (999, 'future')")
    conn.close()
    assert gateway.readiness().ready is False
    assert gateway.readiness().checks["migrations"].startswith("future")