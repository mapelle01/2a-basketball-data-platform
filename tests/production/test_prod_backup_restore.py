"""FASE 13 — Backup & restore: SQLite online backup + pg_dump/pg_restore smoke.

The PostgreSQL smoke test shells out to the real ``pg_dump``/``pg_restore`` tools
(``/opt/homebrew/bin``); it is skipped when they are not installed.
"""

import shutil
import subprocess
from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.match.model import Match
from feb_score.domain.value_objects import CompetitionId, ExternalId, MatchId, SeasonCode
from feb_score.infrastructure.persistence.connection import SqliteDatabase


def _match():
    return Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )


def test_sqlite_backup_and_restore_round_trip(tmp_path):
    live = SqliteDatabase(str(tmp_path / "live.db"))
    live.migrate()
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    SqliteMatchRepository(live).save(_match())

    backup = live.backup(str(tmp_path / "backup.sqlite3"))
    assert __import__("os").path.exists(backup)

    # Corrupt/destroy the live database, then restore from the backup.
    __import__("os").remove(live.path)
    live.restore(backup)
    restored = SqliteMatchRepository(live).get_by_external_id(ExternalId("2513600"))
    assert restored is not None
    assert restored.competition_id.value == "feb-comp"


def test_sqlite_backup_captures_wal_committed_state(tmp_path):
    """Backup uses the SQLite online-backup API, so it includes every committed
    transaction even while the database is in WAL mode."""
    live = SqliteDatabase(str(tmp_path / "live.db"), settings=__import__(
        "feb_score.infrastructure.config", fromlist=["Settings"]
    ).Settings())
    live.migrate()
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    SqliteMatchRepository(live).save(_match())
    backup = live.backup(str(tmp_path / "b.sqlite3"))
    fresh = SqliteDatabase(str(tmp_path / "copy.db"))
    fresh.restore(backup)
    assert SqliteMatchRepository(fresh).get_by_external_id(ExternalId("2513600")) is not None


def _tools():
    dump = shutil.which("pg_dump")
    restore = shutil.which("psql")
    if not (dump and restore):
        pytest.skip("pg_dump/psql not installed")
    return dump, restore


def test_pg_dump_restore_round_trip(pg_dsn, pg_db):
    dump_bin, psql_bin = _tools()

    pg_db.migrate()
    from feb_score.infrastructure.persistence.postgres.repositories import PgMatchRepository

    PgMatchRepository(pg_db).save(_match())

    schema = pg_db.schema
    dump_path = f"/tmp/feb_pg_dump_{uuid4().hex}.sql"
    # Plain-format, schema-scoped dump: SQL text that recreates schema + data.
    subprocess.run(
        [dump_bin, "-h", "127.0.0.1", "-p", "5433", "-U", "postgres",
         "-d", "feb_test", "--schema", schema, "--format=plain", "-f", dump_path],
        check=True, capture_output=True,
    )
    assert b"CREATE SCHEMA" in open(dump_path, "rb").read()

    # Destroy the schema, then restore from the dump (the dump recreates it).
    conn = pg_db.connect()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.close()
    with open(dump_path) as fh:
        subprocess.run(
            [psql_bin, "-h", "127.0.0.1", "-p", "5433", "-U", "postgres", "-d", "feb_test"],
            stdin=fh, check=True, capture_output=True,
        )

    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase

    restored = PgDatabase(pg_dsn, schema=schema)
    match = PgMatchRepository(restored).get_by_external_id(ExternalId("2513600"))
    assert match is not None
    assert match.competition_id.value == "feb-comp"