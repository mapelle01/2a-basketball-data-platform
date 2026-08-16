"""FASE 23.6 — season analytics query indexes (cross-backend).

The six analytics reads filter exclusively by ``season_code``, so migration
``analytics_indexes`` (SQLite #4 / PostgreSQL #3) adds season-first indexes on
``match_player_stats`` and ``match_team_stats``. These tests verify the indexes
exist after migrate, that re-migrating is idempotent, and that the analytics
queries still honour season filtering, deterministic ordering and limits on
both backends.
"""

from __future__ import annotations

import pytest

from feb_score.domain.statistics.model import PlayerStats, TeamStats

INDEXES = {
    "idx_player_stats_season_scan": "match_player_stats",
    "idx_team_stats_season_scan": "match_team_stats",
}


def _existing_indexes(db) -> set:
    from feb_score.infrastructure.persistence.connection import SqliteDatabase
    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase

    conn = db.connect()
    try:
        if isinstance(db, SqliteDatabase):
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
            return {r["name"] for r in rows}
        if isinstance(db, PgDatabase):
            rows = conn.execute(
                "SELECT indexname AS name FROM pg_indexes"
                " WHERE schemaname = current_schema()"
            ).fetchall()
            return {r["name"] for r in rows}
        raise TypeError(type(db))
    finally:
        conn.close()


def test_analytics_indexes_created_by_migration(backend):
    db = backend.make_db()
    present = _existing_indexes(db)
    for name, table in INDEXES.items():
        assert name in present, name


def test_re_migrate_is_idempotent(backend):
    db = backend.make_db()
    first = _existing_indexes(db)
    db.migrate()  # re-run: must be a no-op
    second = _existing_indexes(db)
    assert second == first
    assert len([i for i in second if i.startswith("idx_")]) == len(
        [i for i in first if i.startswith("idx_")]
    )


def _ps(pid, pts, reb=0, ast=0):
    return PlayerStats(
        player_external_id=pid, team_external_id="TX",
        points=pts, rebounds=reb, assists=ast, steals=0, blocks=0, turnovers=0, minutes=0.0,
    )


def _ts(tid, pf, pa):
    return TeamStats(
        team_external_id=tid, points_for=pf, points_against=pa,
        field_goals_made=10, field_goals_attempted=20, three_points_made=3,
        three_points_attempted=8, free_throws_made=4, free_throws_attempted=6,
        turnovers=5, rebounds=20,
    )


def test_analytics_queries_with_indexes_keep_season_filter_order_limit(backend):
    db = backend.make_db()
    repo = backend.repo(db, "stats")
    repo.save_player_stats("M1", "2025-2026", [_ps("PA", 30, reb=5, ast=3), _ps("PB", 20, reb=8, ast=7)])
    repo.save_player_stats("M2", "2025-2026", [_ps("PA", 20, reb=4, ast=2), _ps("PB", 25, reb=7, ast=5), _ps("PC", 5, reb=1, ast=1)])
    repo.save_player_stats("M9", "2024-2025", [_ps("PA", 999, reb=999, ast=999)])
    repo.save_team_stats("M1", "2025-2026", [_ts("T1", 80, 70), _ts("T2", 70, 80)])
    repo.save_team_stats("M2", "2025-2026", [_ts("T1", 75, 90), _ts("T2", 90, 75)])

    agg = list(repo.list_season_player_aggregates("2025-2026"))
    assert [a.player_external_id for a in agg] == ["PA", "PB", "PC"]
    assert agg[0].points == 50  # season-isolated (999-pt 2024-2025 excluded)

    assert [a.player_external_id for a in repo.list_season_player_aggregates("2025-2026", 1)] == ["PA"]

    lb = list(repo.list_season_player_leaderboard("2025-2026", "points", 2))
    assert [e.rank for e in lb] == [1, 2]
    assert [e.player_external_id for e in lb] == ["PA", "PB"]

    metrics = list(repo.list_season_player_metrics("2025-2026"))
    by_id = {m.player_external_id: m for m in metrics}
    assert abs(by_id["PA"].points_per_game - 25.0) < 1e-9

    teams = list(repo.list_season_team_aggregates("2025-2026"))
    assert [t.team_external_id for t in teams] == ["T1", "T2"]

    team_lb = list(repo.list_season_team_leaderboard("2025-2026", "classification"))
    assert [e.team_external_id for e in team_lb] == ["T2", "T1"]  # T2 has +5 diff

    team_metrics = list(repo.list_season_team_metrics("2025-2026"))
    by_team = {m.team_external_id: m for m in team_metrics}
    assert abs(by_team["T1"].win_percentage - 50.0) < 1e-9