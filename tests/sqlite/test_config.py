"""FASE 10 — Configuration: explicit, injectable, environment-overridable."""

import os

import pytest

from feb_score.infrastructure.config import Settings, settings_from_env
from feb_score.infrastructure.persistence.connection import SqliteDatabase


def test_settings_defaults_are_sane():
    s = Settings()
    assert s.busy_timeout_ms == 5000
    assert s.wal is True
    assert s.foreign_keys is True
    assert s.dispatch_batch_size == 100
    assert s.timezone == "UTC"


def test_settings_from_env_honors_overrides(monkeypatch):
    monkeypatch.setenv("FEB_SCORE_DB", "/tmp/x.db")
    monkeypatch.setenv("FEB_SCORE_BUSY_TIMEOUT", "1234")
    monkeypatch.setenv("FEB_SCORE_DISPATCH_BATCH", "7")
    s = settings_from_env()
    assert s.db_path == "/tmp/x.db"
    assert s.busy_timeout_ms == 1234
    assert s.dispatch_batch_size == 7


def test_database_applies_settings(sqlite_db, db_path):
    assert SqliteDatabase(db_path).settings.busy_timeout_ms == 5000
    # the injected path is the source of truth
    conn = sqlite_db.connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] in ("wal", "memory")
    finally:
        conn.close()


def test_database_without_wal(tmp_path):
    path = str(tmp_path / "no-wal.db")
    db = SqliteDatabase(path, settings=Settings(wal=False))
    db.migrate()
    conn = db.connect()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode != "wal"