"""PostgreSQL infrastructure: connection lifecycle, migrations and transactions.

Mirrors the SQLite layer contract-for-contract:

* ``PgDatabase`` — owns the DSN, connection factory and migration runner. Each
  connection sets ``dict_row`` row factory, ``autocommit=False`` and a UTC
  session timezone so naive-UTC domain timestamps are stored/compared correctly.
* ``PgUnitOfWork`` — "one command = one transaction". Installs a connection on a
  ``ContextVar`` so every PostgreSQL repository/event-store write in the same
  process shares ONE transaction. Commit on success, full rollback on error.
* Migrations are versioned in a ``schema_version`` table over an ordered
  ``MIGRATIONS`` list, applied exactly once per version, each in its own
  transaction (reproducible from scratch or in place).

Configuration policy (FASE 12): no credentials are hardcoded. The DSN comes from
the environment (``FEB_SCORE_DATABASE_URL``); the ``PgDatabase`` constructor is
injectable for tests.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import psycopg
from psycopg.rows import dict_row

from ...config import Settings
from ..errors import (
    ConstraintViolationError,
    DatabaseUnavailableError,
    DeadlockError,
    InfrastructureError,
    SerializationConflictError,
    StaleVersionError,
)
from .errors import translate_pg_error

_active_pg_conn: contextvars.ContextVar = contextvars.ContextVar(
    "feb_score_active_pg_conn", default=None
)

_MIGRATIONS_DIR = Path(__file__).with_name("migrations")

# Retryable (or otherwise significant) PostgreSQL SQLSTATEs mapped to the
# infrastructure taxonomy. Anything else surfaces as ``InfrastructureError``.
_SERIALIZATION_FAILURE = "40001"
_DEADLOCK = "40P01"


@dataclass(frozen=True)
class PgMigration:
    version: int
    name: str
    script: str


MIGRATIONS: List[PgMigration] = [
    PgMigration(
        version=1,
        name="initial",
        script=(_MIGRATIONS_DIR / "001_initial.sql").read_text(),
    ),
    PgMigration(
        version=2,
        name="match_stats",
        script=(_MIGRATIONS_DIR / "002_match_stats.sql").read_text(),
    ),
    PgMigration(
        version=3,
        name="analytics_indexes",
        script=(_MIGRATIONS_DIR / "003_analytics_indexes.sql").read_text(),
    ),
]


def pg_active_connection():
    """The transaction connection installed by an active ``PgUnitOfWork``."""
    return _active_pg_conn.get()


def _split_statements(script: str) -> List[str]:
    """Split a DDL script into individual statements (same policy as SQLite:
    no stored procedures, safe to split on ';')."""
    statements: List[str] = []
    buffer: List[str] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        buffer.append(line)
        if line.endswith(";"):
            statements.append(" ".join(buffer))
            buffer = []
    if buffer:
        statements.append(" ".join(buffer))
    return statements


class PgDatabase:
    def __init__(
        self,
        dsn: str,
        settings: Optional[Settings] = None,
        schema: Optional[str] = None,
    ) -> None:
        self.dsn = dsn
        self.settings = settings or Settings()
        self.schema = schema  # per-test isolation: search_path for this db handle

    def connect(self):
        """Standalone connection: every statement autocommits immediately
        (SQLite-style), used by repository/event-store calls OUTSIDE a unit of
        work."""
        return self._connect(autocommit=True)

    def connect_txn(self):
        """Connection for explicit transaction control (unit of work, migrate):
        the first statement opens a transaction closed by commit()/rollback()."""
        return self._connect(autocommit=False)

    def _connect(self, autocommit: bool):
        conn = psycopg.connect(
            self.dsn,
            autocommit=autocommit,
            row_factory=dict_row,
            # a runaway query cannot hold a lock/connection indefinitely
            connect_timeout=round(self.settings.pg_connect_timeout_ms / 1000),
        )
        with conn.cursor() as cur:
            # SET-based (not an `options` conninfo param) so a search_path given
            # in the DSN itself is preserved.
            cur.execute(f"SET statement_timeout = {self.settings.pg_statement_timeout_ms}")
            cur.execute("SET TIME ZONE 'UTC'")
            if self.schema:
                # SET search_path cannot take a bound parameter; identifier is
                # escaped with psycopg.sql so per-test schema names stay safe.
                stmt = psycopg.sql.SQL("SET search_path TO {}, public").format(
                    psycopg.sql.Identifier(self.schema)
                )
                cur.execute(stmt)
        return conn

    # ---------------------------------------------------------------- migrate
    def migrate(self) -> None:
        """Create/upgrade the schema to the latest version.

        Versioned and reproducible: each migration runs in its OWN transaction and
        its version is recorded in ``schema_version`` only after success. A partial
        failure rolls back and leaves the version unrecorded, so re-running retries
        it cleanly. Versions must be strictly monotonic ascending.
        """
        versions = [m.version for m in MIGRATIONS]
        if any(b <= a for a, b in zip(versions, versions[1:])):
            raise ValueError("MIGRATIONS versions must be strictly increasing")
        conn = self.connect_txn()
        try:
            if self.schema:
                # Unqualified names resolve to the FIRST existing schema in
                # search_path; create the target schema before touching tables.
                conn.execute(
                    psycopg.sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        psycopg.sql.Identifier(self.schema)
                    )
                )
                conn.commit()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                " version INT PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
            conn.commit()
            current = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()["v"]
            # Refuse a future/unknown schema: a database migrated by a NEWER
            # binary must not be downgraded or blindly "completed" by this one.
            max_known = max(m.version for m in MIGRATIONS)
            if current > max_known:
                raise InfrastructureError(
                    f"database schema version {current} is newer than the supported maximum "
                    f"{max_known}; upgrade this application before continuing"
                )
            for migration in MIGRATIONS:
                if migration.version <= current:
                    continue
                self._apply_migration(conn, migration)
        finally:
            conn.close()

    def _apply_migration(self, conn, migration: PgMigration) -> None:
        statements = _split_statements(migration.script)
        if not statements:
            raise ValueError(f"migration {migration.version} ({migration.name}) is empty")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, name) VALUES (%s, %s)",
                (migration.version, migration.name),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------ misc
    def schema_version(self) -> int:
        conn = self.connect()
        try:
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
            return int(row["v"])
        finally:
            conn.close()

    def unit_of_work(self) -> "PgUnitOfWork":
        return PgUnitOfWork(self)

    def event_store(self):
        from .event_store import PgEventStore

        return PgEventStore(self)


class PgUnitOfWork:
    """Context manager: open a single PostgreSQL transaction shared by all
    PostgreSQL repositories (same contract as ``SqliteUnitOfWork``)."""

    def __init__(self, db: PgDatabase) -> None:
        self.db = db
        self._conn = None
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> "PgUnitOfWork":
        self._conn = self.db.connect_txn()  # autocommit=False: first statement opens a txn
        self._token = _active_pg_conn.set(self._conn)
        return self

    def append_events(self, events: List[object]) -> None:
        if not events:
            return
        from .event_store import PgEventStore

        PgEventStore(self.db).append_many(events)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _active_pg_conn.reset(self._token)
        conn = self._conn
        self._conn = None
        try:
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()