"""FASE 12 — PostgreSQL test harness.

Provides:
* ``pg_dsn`` fixture: the PostgreSQL DSN (env ``FEB_SCORE_PG_DSN``, default a
  local test server). Tests are SKIPPED when no PostgreSQL is reachable.
* ``backend`` parametrized fixture: yields the SAME contract-test suite against
  SQLite and PostgreSQL (per-test isolation: temp file for SQLite, unique schema
  for PostgreSQL).
* ``pg_db`` fixture: an isolated, migrated PostgreSQL database for pg-specific
  tests.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sqlite"))

import pytest

from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_dispatcher import SyncEventDispatcher
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.event_store import PgEventStore
from feb_score.infrastructure.wiring import PgGateway, SqliteGateway

DEFAULT_PG_DSN = "postgresql://postgres@127.0.0.1:5433/feb_test"


def _pg_reachable(dsn: str) -> bool:
    try:
        db = PgDatabase(dsn)
        conn = db.connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:  # noqa: BLE001 - availability probe
        return False


@pytest.fixture(scope="session")
def pg_dsn():
    dsn = __import__("os").environ.get("FEB_SCORE_PG_DSN", DEFAULT_PG_DSN)
    if not _pg_reachable(dsn):
        pytest.skip(f"PostgreSQL not reachable at {dsn}; set FEB_SCORE_PG_DSN")
    return dsn


class _Backend:
    name = ""

    def make_db(self):
        raise NotImplementedError

    def reopen(self, db):
        """A FRESH handle to the SAME underlying store (restart semantics)."""
        raise NotImplementedError

    def gateway(self, db, logger=None):
        raise NotImplementedError

    def event_store(self, db):
        raise NotImplementedError

    def dispatcher(self, db, publisher):
        return SyncEventDispatcher(db, publisher)

    def repo(self, db, kind):
        """A concrete repository instance for `kind` (match/player/team/...)."""
        raise NotImplementedError


class SqliteBackend(_Backend):
    name = "sqlite"

    def __init__(self, tmp_path):
        self.tmp = tmp_path

    def make_db(self):
        db = SqliteDatabase(str(self.tmp / f"feb_{uuid.uuid4().hex[:8]}.db"))
        db.migrate()
        return db

    def reopen(self, db):
        return SqliteDatabase(db.path)

    def gateway(self, db, logger=None):
        return SqliteGateway(db, logger=logger)

    def event_store(self, db):
        return SqliteEventStore(db)

    def repo(self, db, kind):
        from feb_score.infrastructure.persistence import repositories as R

        return {
            "match": R.SqliteMatchRepository,
            "player": R.SqlitePlayerRepository,
            "team": R.SqliteTeamRepository,
            "competition": R.SqliteCompetitionRepository,
            "correction": R.SqliteCorrectionRepository,
            "standing": R.SqliteStandingRepository,
            "leaderboard": R.SqliteLeaderboardRepository,
            "rating": R.SqliteRatingRepository,
            "publication": R.SqlitePublicationRepository,
            "idempotency": R.SqliteIdempotencyRepository,
        }[kind](db)


class PostgresBackend(_Backend):
    name = "postgres"

    def __init__(self, dsn):
        self.dsn = dsn
        self.schemas = []

    def make_db(self):
        schema = f"s_{uuid.uuid4().hex[:12]}"
        self.schemas.append(schema)
        db = PgDatabase(self.dsn, schema=schema)
        db.migrate()
        return db

    def reopen(self, db):
        return PgDatabase(db.dsn, schema=db.schema)

    def gateway(self, db, logger=None):
        return PgGateway(db, logger=logger)

    def event_store(self, db):
        return PgEventStore(db)

    def repo(self, db, kind):
        from feb_score.infrastructure.persistence.postgres import repositories as R

        return {
            "match": R.PgMatchRepository,
            "player": R.PgPlayerRepository,
            "team": R.PgTeamRepository,
            "competition": R.PgCompetitionRepository,
            "correction": R.PgCorrectionRepository,
            "standing": R.PgStandingRepository,
            "leaderboard": R.PgLeaderboardRepository,
            "rating": R.PgRatingRepository,
            "publication": R.PgPublicationRepository,
            "idempotency": R.PgIdempotencyRepository,
        }[kind](db)

    def cleanup(self):
        for schema in self.schemas:
            try:
                db = PgDatabase(self.dsn)
                conn = db.connect()
                conn.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
                conn.close()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request, tmp_path, pg_dsn):
    if request.param == "sqlite":
        return SqliteBackend(tmp_path)
    backend = PostgresBackend(pg_dsn)
    request.addfinalizer(backend.cleanup)
    return backend


@pytest.fixture
def pg_db(pg_dsn):
    backend = PostgresBackend(pg_dsn)
    db = backend.make_db()
    yield db
    backend.cleanup()


@pytest.fixture
def pg_gateway(pg_db):
    return PgGateway(pg_db, logger=None)


@pytest.fixture
def pg_client(pg_db):
    from fastapi.testclient import TestClient

    from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
    from feb_score.api.main import create_app
    from feb_score.infrastructure.logging import RecordingLogger

    gateway = PgGateway(pg_db, logger=RecordingLogger())
    auth = ApiKeyAuthenticationProvider({"system-key": Principal(id="api", role="system")})
    return TestClient(create_app(gateway, logger=RecordingLogger(), auth=auth))