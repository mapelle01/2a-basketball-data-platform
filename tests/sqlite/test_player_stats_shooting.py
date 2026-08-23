"""Per-player shooting/fouls/+/- survive persistence WITHOUT a schema change.

The new PlayerStats fields ride in the existing ``data`` JSON blob of
match_player_stats, so a save→reopen→list round-trip preserves them with no
migration. Old rows (no shooting) come back as None (back-compat).
"""
from __future__ import annotations

import pytest

from feb_score.domain.statistics.model import PlayerStats
from feb_score.domain.value_objects import SeasonCode
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import SqliteMatchStatsRepository

SEASON = SeasonCode("2025-2026")


def _ps(**kw) -> PlayerStats:
    base = dict(player_external_id="p1", team_external_id="t1", points=27,
                rebounds=3, assists=2, steals=1, blocks=0, turnovers=2, minutes=30.0)
    base.update(kw)
    return PlayerStats(**base)


def test_shooting_survives_sqlite_roundtrip_no_migration(sqlite_db, db_path):
    repo = SqliteMatchStatsRepository(sqlite_db)
    ps = _ps(field_goals_made=10, field_goals_attempted=15, three_points_made=8,
             three_points_attempted=12, free_throws_made=1, free_throws_attempted=2,
             fouls=3, plus_minus=-4)
    repo.save_player_stats("m1", SEASON, [ps])

    fresh = SqliteMatchStatsRepository(SqliteDatabase(db_path))  # reopen
    got = list(fresh.list_player_stats("m1"))
    assert len(got) == 1
    g = got[0]
    assert (g.field_goals_made, g.field_goals_attempted) == (10, 15)
    assert (g.three_points_made, g.three_points_attempted) == (8, 12)
    assert (g.free_throws_made, g.free_throws_attempted) == (1, 2)
    assert g.fouls == 3 and g.plus_minus == -4


def test_backcompat_missing_shooting_reads_as_none(sqlite_db):
    repo = SqliteMatchStatsRepository(sqlite_db)
    repo.save_player_stats("m2", SEASON, [_ps()])  # no shooting supplied
    g = list(repo.list_player_stats("m2"))[0]
    assert g.three_points_made is None and g.fouls is None and g.plus_minus is None
    assert g.points == 27  # core stats intact


def test_validation():
    with pytest.raises(ValueError):
        _ps(three_points_made=5, three_points_attempted=3)   # attempted < made
    with pytest.raises(ValueError):
        _ps(field_goals_made=-1)
    with pytest.raises(ValueError):
        _ps(fouls=-1)
