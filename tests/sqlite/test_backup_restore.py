"""FASE 10 — Backup/restore: online SQLite backup preserves ALL persisted data,
including pending (undelivered) events, across a catastrophic file loss."""

import os

from feb_score.application.commands.commands import ComputePlayerRatingCommand
from feb_score.application.use_cases.handlers import ComputePlayerRatingHandler
from feb_score.domain.value_objects import ExternalId
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.event_store import SqliteEventStore
from feb_score.infrastructure.persistence.repositories import (
    SqliteCompetitionRepository,
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteRatingRepository,
    SqliteTeamRepository,
)

from sqlite_helpers import cmd, finalized_match, make_competition, make_player, make_team, run


def _wipe(path):
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)


def test_backup_and_restore_preserves_everything(sqlite_db, db_path, tmp_path):
    match_repo = SqliteMatchRepository(sqlite_db)
    rating_repo = SqliteRatingRepository(sqlite_db)
    match_repo.save(finalized_match())
    run(
        sqlite_db,
        ComputePlayerRatingHandler(match_repo, rating_repo),
        ComputePlayerRatingCommand(
            **cmd({
                "player_external_id": "pl-1", "season_code": "2025-2026",
                "rating_version": "v1.0", "competition_id": "feb-comp",
            })
        ),
    )
    SqlitePlayerRepository(sqlite_db).save(make_player())
    SqliteTeamRepository(sqlite_db).save(make_team())
    SqliteCompetitionRepository(sqlite_db).save(make_competition())

    pending_before = SqliteEventStore(sqlite_db).pending_count()
    assert pending_before >= 1

    backup_path = str(tmp_path / "feb-backup.db")
    sqlite_db.backup(backup_path)
    assert os.path.exists(backup_path)

    # Catastrophic loss: delete the live database and its WAL files.
    _wipe(db_path)

    # Restore from the backup and reopen with a brand-new SqliteDatabase.
    restored = SqliteDatabase(db_path)
    restored.restore(backup_path)
    restored.migrate()  # backup is at the current version; this is a no-op

    assert SqliteMatchRepository(restored).get_by_external_id(ExternalId("2513600")) is not None
    assert len(SqliteRatingRepository(restored).list_all()) == 1
    assert SqlitePlayerRepository(restored).get_by_external_id(ExternalId("pl-987")) is not None
    assert SqliteTeamRepository(restored).get_by_external_id(ExternalId("team-123")) is not None
    assert SqliteCompetitionRepository(restored).get_by_external_id(ExternalId("feb-comp")) is not None
    assert SqliteEventStore(restored).pending_count() == pending_before


def test_restore_from_older_schema_then_migrate(sqlite_db, db_path, tmp_path):
    """A backup taken before a future destructive migration restores and migrates."""
    SqlitePlayerRepository(sqlite_db).save(make_player())
    backup_path = str(tmp_path / "feb-old.db")
    sqlite_db.backup(backup_path)

    _wipe(db_path)
    restored = SqliteDatabase(db_path)
    restored.restore(backup_path)
    restored.migrate()
    assert SqlitePlayerRepository(restored).get_by_external_id(ExternalId("pl-987")) is not None
    assert restored.user_version > 0