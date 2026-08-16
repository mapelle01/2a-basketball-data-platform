"""FASE 23.7 — season analytics production validator tests (PostgreSQL).

The validator ``validate_season_analytics_production.py`` is the single
read-only gate for the whole season-analytics surface (FASE 23.1-23.6). These
tests prove it actually gates: a production-shaped dataset (364 matches /
26 rounds x 14 / 28 teams / season-isolation row) must PASS every block, while
corrupted data must be reported as FAIL. All checks run through the real
validator functions, not re-implementations.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository

from validate_season_analytics_production import (
    SEASON,
    run_validations,
    validate_production,
)

TEAMS = [f"TEAM-{i:02d}" for i in range(1, 29)]
PLAYERS = [f"PL-{i:03d}" for i in range(1, 301)]


def _seed_full(db) -> None:
    """Deterministic production-equivalent dataset on an isolated PG schema."""
    rng = random.Random(2304)
    repo = PgMatchStatsRepository(db)
    player_team = {p: TEAMS[i % 28] for i, p in enumerate(PLAYERS)}

    with db.connect() as conn:
        match_id = 0
        for rnd in range(1, 27):
            teams = TEAMS[:]
            rng.shuffle(teams)
            for g in range(14):
                match_id += 1
                mid = f"M{match_id}"
                home, away = teams[2 * g], teams[2 * g + 1]
                home_score = rng.randint(65, 105)
                away_score = rng.randint(60, 110)
                while away_score == home_score:
                    away_score = rng.randint(60, 110)
                data = {
                    "external_id": mid, "match_id": mid,
                    "competition_id": "segunda-feb", "season_code": SEASON,
                    "round_number": rnd, "home_team_id": home, "away_team_id": away,
                    "status": "FINALIZED", "version": 1,
                }
                conn.execute(
                    "INSERT INTO matches (match_id, external_id, competition_id,"
                    " season_code, status, version, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (mid, mid, "segunda-feb", SEASON, "FINALIZED", 1, json.dumps(data)),
                )
                for team, pf, pa in ((home, home_score, away_score),
                                     (away, away_score, home_score)):
                    fgm = rng.randint(22, 38)
                    fga = fgm + rng.randint(15, 30)
                    tpm = rng.randint(5, 15)
                    tpa = tpm + rng.randint(8, 18)
                    ftm = rng.randint(8, 22)
                    fta = ftm + rng.randint(3, 10)
                    repo.save_team_stats(mid, SEASON, [
                        TeamStats(
                            team_external_id=team, points_for=pf, points_against=pa,
                            field_goals_made=fgm, field_goals_attempted=fga,
                            three_points_made=tpm, three_points_attempted=tpa,
                            free_throws_made=ftm, free_throws_attempted=fta,
                            turnovers=rng.randint(8, 18), rebounds=rng.randint(28, 45),
                        )
                    ])
                for team in (home, away):
                    squad = [p for p in PLAYERS if player_team[p] == team]
                    rng.shuffle(squad)
                    for p in squad[:11]:
                        repo.save_player_stats(mid, SEASON, [
                            PlayerStats(
                                player_external_id=p, team_external_id=team,
                                points=rng.randint(0, 30), rebounds=rng.randint(0, 12),
                                assists=rng.randint(0, 9), steals=rng.randint(0, 5),
                                blocks=rng.randint(0, 4), turnovers=rng.randint(0, 6),
                                minutes=rng.choice([18.0, 22.0, 25.0, 28.0, 30.0, 32.0, 35.0]),
                            )
                        ])
        # season-isolation contamination row
        data = {
            "external_id": "M999", "match_id": "M999", "competition_id": "segunda-feb",
            "season_code": "2024-2025", "round_number": 1,
            "home_team_id": "TEAM-01", "away_team_id": "TEAM-02",
            "status": "FINALIZED", "version": 1,
        }
        conn.execute(
            "INSERT INTO matches (match_id, external_id, competition_id,"
            " season_code, status, version, data)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("M999", "M999", "segunda-feb", "2024-2025", "FINALIZED", 1, json.dumps(data)),
        )
        repo.save_team_stats("M999", "2024-2025", [
            TeamStats(team_external_id="TEAM-01", points_for=9999, points_against=0,
                      field_goals_made=1, field_goals_attempted=2, three_points_made=0,
                      three_points_attempted=1, free_throws_made=1, free_throws_attempted=2,
                      turnovers=1, rebounds=1)
        ])
        repo.save_player_stats("M999", "2024-2025", [
            PlayerStats(player_external_id="PL-001", team_external_id="TEAM-01",
                        points=9999, rebounds=999, assists=999, steals=99, blocks=99,
                        turnovers=99, minutes=99.0)
        ])


def test_validator_passes_on_production_shaped_data(pg_db):
    _seed_full(pg_db)
    code, failures = run_validations(pg_db, SEASON)
    assert code == 0
    assert failures == []


def test_validator_reports_missing_match(pg_db):
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        conn.execute(
            "DELETE FROM matches WHERE season_code = %s"
            " AND external_id = (SELECT external_id FROM matches"
            " WHERE season_code = %s LIMIT 1)",
            (SEASON, SEASON),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("matches total" in f for f in failures)


def test_validator_reports_null_round_number(pg_db):
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        conn.execute(
            "UPDATE matches SET data = jsonb_set(data, '{round_number}', '0')"
            " WHERE season_code = %s AND external_id = (SELECT external_id"
            " FROM matches WHERE season_code = %s LIMIT 1)",
            (SEASON, SEASON),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code != 0
    assert any("round_number" in f for f in failures)


def test_validator_ignores_stray_competition_rows_and_rounds_minutes(pg_db):
    """FASE 23.8 production findings: the league ``matches`` scoping and the
    single-precision ``minutes_per_game`` round-trip tolerance."""
    _seed_full(pg_db)
    with pg_db.connect() as conn:
        # stray non-league match rows under the same season (no stats, like the
        # smoke-test artifacts found in real production) must not fail the block
        data = {
            "external_id": "M-SMOKE-1", "match_id": "M-SMOKE-1",
            "competition_id": "smoke-comp", "season_code": SEASON,
            "round_number": 1, "home_team_id": "smoke-home", "away_team_id": "smoke-away",
            "status": "SCHEDULED", "version": 1,
        }
        conn.execute(
            "INSERT INTO matches (match_id, external_id, competition_id,"
            " season_code, status, version, data)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("M-SMOKE-1", "M-SMOKE-1", "smoke-comp", SEASON, "SCHEDULED", 1, json.dumps(data)),
        )
        # fractional minutes like real production (single-precision per_game)
        conn.execute(
            "UPDATE match_player_stats SET minutes = 23.333"
            " WHERE season_code = %s AND player_external_id = %s AND match_external_id = %s",
            (SEASON, "PL-001", "M1"),
        )
    code, failures = run_validations(pg_db, SEASON)
    assert code == 0
    assert failures == []


def test_validate_production_requires_dsn(monkeypatch):
    monkeypatch.delenv("FEB_SCORE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert validate_production() == 1