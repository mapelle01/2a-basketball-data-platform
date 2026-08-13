"""SQLite infrastructure: connection lifecycle, migrations and transactions.

Single configuration point for the whole persistence layer:

* ``SqliteDatabase`` — owns the database path, connection factory, migration runner,
  and online backup/restore.
* ``SqliteUnitOfWork`` — "one command = one transaction" boundary. While active it
  installs a connection on a ``ContextVar`` so every repository/event-store write in
  the same process shares ONE transaction. Commit on success, full rollback on error.
* Migrations use ``PRAGMA user_version`` over an ordered ``MIGRATIONS`` list, so a
  database can be created from scratch or upgraded in place reproducibly.

Configuration policy (FASE 10): no critical configuration is hardcoded. The only
connection parameters are ``path`` (constructor) plus the fixed pragmas below; they
can be overridden per environment from the entrypoint. Timestamps in the domain use
timezone-naive UTC (``datetime.utcnow``); this is a documented, deliberate choice.
"""

from __future__ import annotations

import contextvars
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..config import Settings
from .errors import InfrastructureError

_active_conn: contextvars.ContextVar[Optional[sqlite3.Connection]] = contextvars.ContextVar(
    "feb_score_active_conn", default=None
)

_MIGRATIONS_DIR = Path(__file__).with_name("migrations")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    destructive: bool
    script: str


MIGRATIONS: List[Migration] = [
    Migration(
        version=1,
        name="initial",
        destructive=False,
        script=(_MIGRATIONS_DIR / "001_initial.sql").read_text(),
    ),
    Migration(
        version=2,
        name="match_integrity",
        destructive=True,
        script=(_MIGRATIONS_DIR / "002_match_integrity.sql").read_text(),
    ),
]


def _split_statements(script: str) -> List[str]:
    """Split a DDL script into individual statements for transactional execution.

    Handles ``--`` line comments and tolerates leading/trailing whitespace.
    DDL scripts contain no stored procedures or triggers, so a naive split on ';'
    is safe here.
    """
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


def active_connection() -> Optional[sqlite3.Connection]:
    """The transaction connection installed by an active ``SqliteUnitOfWork``."""
    return _active_conn.get()


class SqliteDatabase:
    def __init__(self, path: str, settings: Optional[Settings] = None) -> None:
        self.path = str(path)
        self.settings = settings or Settings()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        # Autocommit per statement: each repository op is its own transaction when no
        # unit of work is active. An explicit BEGIN IMMEDIATE (unit of work) still
        # opens a transaction that only COMMIT/ROLLBACK closes.
        conn.isolation_level = None
        if self.settings.foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {self.settings.busy_timeout_ms}")
        if self.path != ":memory:" and self.settings.wal:
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ------------------------------------------------------------------ config
    @property
    def user_version(self) -> int:
        conn = self.connect()
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    # ----------------------------------------------------------------- migrate
    def migrate(self) -> None:
        """Create/upgrade the schema to the latest version.

        Guarantees (FASE 10 hardening):
        * migrations are ordered and applied exactly once (``user_version`` skip);
        * versions must be strictly monotonic ascending;
        * each migration runs in its OWN transaction — a partial failure rolls back
          and leaves ``user_version`` untouched, so re-running retries it cleanly;
        * DESTRUCTIVE migrations get an automatic online backup (``<db>.pre-migrate-<v>.sqlite3``)
          before they run, so a bad upgrade can always be rolled back from disk.
        """
        versions = [m.version for m in MIGRATIONS]
        if any(b <= a for a, b in zip(versions, versions[1:])):
            raise ValueError("MIGRATIONS versions must be strictly increasing")
        conn = self.connect()
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            # Refuse a future/unknown schema: a database written by a NEWER binary
            # must not be silently skipped or downgraded (FASE 13 hardening).
            max_known = max(m.version for m in MIGRATIONS)
            if current > max_known:
                raise InfrastructureError(
                    f"database schema version {current} is newer than the supported maximum "
                    f"{max_known}; upgrade this application before continuing"
                )
            for migration in MIGRATIONS:
                if migration.version <= current:
                    continue
                if migration.destructive:
                    self._auto_backup(migration)
                self._apply_migration(conn, migration)
        finally:
            conn.close()

    def _apply_migration(self, conn: sqlite3.Connection, migration: Migration) -> None:
        statements = _split_statements(migration.script)
        if not statements:
            raise ValueError(f"migration {migration.version} ({migration.name}) is empty")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {migration.version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _auto_backup(self, migration: Migration) -> None:
        if self.path == ":memory:":
            return
        backup_path = f"{self.path}.pre-migrate-{migration.version}.sqlite3"
        self.backup(backup_path)

    # ---------------------------------------------------------- backup/restore
    def backup(self, target_path: str) -> str:
        """Online backup of the live database (WAL-safe) to ``target_path``.

        Uses the SQLite backup API, so it can run while other connections are
        active and captures every committed transaction. Returns the target path.
        """
        source = self.connect()
        try:
            target = sqlite3.connect(str(target_path))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        return str(target_path)

    def restore(self, from_path: str) -> None:
        """Replace the live database with the file at ``from_path`` (a backup).

        Requires no active writers on ``self.path``. After restore, call
        ``migrate()`` if the backup predates a newer schema.
        """
        src = sqlite3.connect(str(from_path))
        try:
            dest = sqlite3.connect(self.path)
            try:
                src.backup(dest)
            finally:
                dest.close()
        finally:
            src.close()

    def unit_of_work(self) -> "SqliteUnitOfWork":
        return SqliteUnitOfWork(self)

    def event_store(self):
        """Outbox store bound to this database (used by the dispatcher)."""
        from .event_store import SqliteEventStore

        return SqliteEventStore(self)


class SqliteUnitOfWork:
    """Context manager: open a single transaction shared by all repositories.

        with db.unit_of_work() as uow:
            events = handler.handle(command)
            uow.append_events(events)   # same transaction as the aggregate changes

    Commits on clean exit; rolls back completely on any exception.
    """

    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db
        self._conn: Optional[sqlite3.Connection] = None
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> "SqliteUnitOfWork":
        self._conn = self.db.connect()
        self._conn.execute("BEGIN IMMEDIATE")
        self._token = _active_conn.set(self._conn)
        return self

    def append_events(self, events: List[object]) -> None:
        """Persist domain/application events inside the open transaction."""
        if not events:
            return
        from .event_store import SqliteEventStore

        SqliteEventStore(self.db).append_many(events)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _active_conn.reset(self._token)
        conn = self._conn
        self._conn = None
        try:
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()