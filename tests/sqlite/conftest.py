import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from feb_score.infrastructure.persistence.connection import SqliteDatabase


@pytest.fixture
def sqlite_db(tmp_path):
    """A migrated SQLite database on a temp file (survives connection reopens)."""
    path = str(tmp_path / "feb.db")
    db = SqliteDatabase(path)
    db.migrate()
    return db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "feb.db")