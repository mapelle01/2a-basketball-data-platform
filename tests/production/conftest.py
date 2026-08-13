"""Shared fixtures for the FASE 13 production-readiness suite.

The ``pg_*`` fixtures connect to the FASE 12 PostgreSQL test server
(``FEB_SCORE_PG_DSN`` or ``postgresql://postgres@127.0.0.1:5433/feb_test``) and
skip gracefully when it is not reachable (e.g. system-python runs without it).
"""

import os
import uuid

import pytest

import psycopg

_DEFAULT_DSN = "postgresql://postgres@127.0.0.1:5433/feb_test"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "feb.db")


@pytest.fixture
def pg_dsn():
    dsn = os.environ.get("FEB_SCORE_PG_DSN", _DEFAULT_DSN)
    try:
        with psycopg.connect(dsn, connect_timeout=2):
            pass
    except Exception:  # noqa: BLE001 - backend not reachable: skip
        pytest.skip("PostgreSQL test server not reachable")
    return dsn


@pytest.fixture
def pg_schema(pg_dsn):
    """A unique, disposable schema on the test server."""
    schema = f"prod_{uuid.uuid4().hex[:12]}"
    conn = psycopg.connect(pg_dsn, autocommit=True)
    try:
        conn.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        conn.close()
    yield schema
    conn = psycopg.connect(pg_dsn, autocommit=True)
    try:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()


@pytest.fixture
def pg_db(pg_dsn, pg_schema):
    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase

    return PgDatabase(pg_dsn, schema=pg_schema)