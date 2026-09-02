#!/usr/bin/env python3
"""FASE 23.2 — Production Read-Only Validator for Season Team Aggregates.

Connects to PostgreSQL (via FEB_SCORE_DATABASE_URL or DATABASE_URL) in read-only
mode to validate SeasonTeamStats aggregates against raw match_team_stats.

Never prints connection secrets, passwords, or tokens.
Does NOT modify any data.

Usage:
    FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_team_aggregates.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("src"))

from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository


def validate_production(season_code: str = "2025-2026") -> int:
    dsn = os.environ.get("FEB_SCORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: FEB_SCORE_DATABASE_URL / DATABASE_URL not set in environment.")
        return 1

    print("=================================================================")
    print(f"FASE 23.2 — Season Team Aggregates Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        repo = PgMatchStatsRepository(db)

        # 1. Domain aggregates via repository
        aggregates = list(repo.list_season_team_aggregates(season_code))
        num_teams = len(aggregates)

        aggr_games  = sum(a.games_played     for a in aggregates)
        aggr_wins   = sum(a.wins             for a in aggregates)
        aggr_losses = sum(a.losses           for a in aggregates)
        aggr_pf     = sum(a.points_for       for a in aggregates)
        aggr_pa     = sum(a.points_against   for a in aggregates)
        aggr_fgm    = sum(a.field_goals_made       for a in aggregates)
        aggr_fga    = sum(a.field_goals_attempted  for a in aggregates)
        aggr_3pm    = sum(a.three_points_made      for a in aggregates)
        aggr_3pa    = sum(a.three_points_attempted for a in aggregates)
        aggr_ftm    = sum(a.free_throws_made       for a in aggregates)
        aggr_fta    = sum(a.free_throws_attempted  for a in aggregates)
        aggr_to     = sum(a.turnovers  for a in aggregates)
        aggr_reb    = sum(a.rebounds   for a in aggregates)

        # 2. Raw DB totals for cross-check
        conn = db.connect()
        try:
            row_matches = conn.execute(
                "SELECT COUNT(DISTINCT external_id) AS cnt FROM matches WHERE season_code = %s",
                (season_code,),
            ).fetchone()
            num_matches = row_matches["cnt"] if row_matches else 0

            row_stats = conn.execute(
                "SELECT"
                "  COUNT(*)                AS total_rows,"
                "  COUNT(DISTINCT team_external_id) AS total_teams,"
                "  COALESCE(SUM(points_for),           0) AS raw_pf,"
                "  COALESCE(SUM(points_against),       0) AS raw_pa,"
                "  COALESCE(SUM(field_goals_made),     0) AS raw_fgm,"
                "  COALESCE(SUM(field_goals_attempted),0) AS raw_fga,"
                "  COALESCE(SUM(three_points_made),    0) AS raw_3pm,"
                "  COALESCE(SUM(three_points_attempted),0) AS raw_3pa,"
                "  COALESCE(SUM(free_throws_made),     0) AS raw_ftm,"
                "  COALESCE(SUM(free_throws_attempted),0) AS raw_fta,"
                "  COALESCE(SUM(turnovers),            0) AS raw_to,"
                "  COALESCE(SUM(rebounds),             0) AS raw_reb,"
                "  COALESCE(SUM(CASE WHEN points_for > points_against THEN 1 ELSE 0 END), 0) AS raw_wins,"
                "  COALESCE(SUM(CASE WHEN points_for < points_against THEN 1 ELSE 0 END), 0) AS raw_losses"
                " FROM match_team_stats"
                " WHERE season_code = %s",
                (season_code,),
            ).fetchone()

            # Isolation: rows for other seasons
            row_other = conn.execute(
                "SELECT COUNT(*) AS cnt FROM match_team_stats WHERE season_code != %s",
                (season_code,),
            ).fetchone()
            other_rows = row_other["cnt"] if row_other else 0

        finally:
            conn.close()

        raw_rows   = row_stats["total_rows"]
        raw_teams  = row_stats["total_teams"]
        raw_pf     = row_stats["raw_pf"]
        raw_pa     = row_stats["raw_pa"]
        raw_fgm    = row_stats["raw_fgm"]
        raw_fga    = row_stats["raw_fga"]
        raw_3pm    = row_stats["raw_3pm"]
        raw_3pa    = row_stats["raw_3pa"]
        raw_ftm    = row_stats["raw_ftm"]
        raw_fta    = row_stats["raw_fta"]
        raw_to     = row_stats["raw_to"]
        raw_reb    = row_stats["raw_reb"]
        raw_wins   = row_stats["raw_wins"]
        raw_losses = row_stats["raw_losses"]

        print(f"\n1. Partidos persistidos ({season_code}):    {num_matches}")
        print(f"2. Equipos agregados ({season_code}):       {num_teams} (raw distinct: {raw_teams})")
        print(f"3. Filas match_team_stats:                  {raw_rows}")
        print(f"4. Filas otras temporadas (aislamiento):   {other_rows}")

        # Mathematical consistency checks
        print("\n--- Métricas Agregadas vs Tabla Raw ---")
        metrics = [
            ("games_played (sum)",  aggr_games,  raw_rows),   # each row = one team in one match
            ("wins",                aggr_wins,   raw_wins),
            ("losses",              aggr_losses, raw_losses),
            ("points_for",          aggr_pf,     raw_pf),
            ("points_against",      aggr_pa,     raw_pa),
            ("field_goals_made",    aggr_fgm,    raw_fgm),
            ("field_goals_att",     aggr_fga,    raw_fga),
            ("three_points_made",   aggr_3pm,    raw_3pm),
            ("three_points_att",    aggr_3pa,    raw_3pa),
            ("free_throws_made",    aggr_ftm,    raw_ftm),
            ("free_throws_att",     aggr_fta,    raw_fta),
            ("turnovers",           aggr_to,     raw_to),
            ("rebounds",            aggr_reb,    raw_reb),
        ]

        all_match = True
        for name, aggr_val, raw_val in metrics:
            matched = aggr_val == raw_val
            if not matched:
                all_match = False
            status = "MATCH" if matched else f"MISMATCH (diff={aggr_val - raw_val})"
            print(f"  * {name:<25}: Aggregated = {aggr_val:<10} | Raw = {raw_val:<10} [{status}]")

        # Basketball invariant check
        expected_participations = num_matches * 2
        inv_ok = aggr_games == expected_participations
        print(f"\n--- Invariante: participaciones equipo-partido ---")
        print(f"  {num_matches} partidos × 2 = {expected_participations} esperado")
        print(f"  SUM(games_played) = {aggr_games}  [{('OK' if inv_ok else 'MISMATCH')}]")
        print(f"  SUM(wins)         = {aggr_wins}  (esperado {num_matches})")
        print(f"  SUM(losses)       = {aggr_losses}  (esperado {num_matches})")
        if not inv_ok:
            all_match = False

        # Leaders
        if aggregates:
            best_wins  = max(aggregates, key=lambda a: a.wins)
            best_pf    = max(aggregates, key=lambda a: a.points_for)
            best_pa    = max(aggregates, key=lambda a: a.points_against)
            most_games = max(aggregates, key=lambda a: a.games_played)

            print("\n--- Líderes de Temporada ---")
            print(f"  * Más victorias       : {best_wins.team_external_id} ({best_wins.wins}W-{best_wins.losses}L)")
            print(f"  * Más puntos a favor  : {best_pf.team_external_id} ({best_pf.points_for} pts)")
            print(f"  * Más puntos en contra: {best_pa.team_external_id} ({best_pa.points_against} pts)")
            print(f"  * Más partidos        : {most_games.team_external_id} ({most_games.games_played} PJ)")

        print("\n=================================================================")
        if all_match and num_teams == raw_teams:
            print("RESULTADO VALIDACIÓN: PASS — Consistencia matemática e integridad al 100%.")
            print("=================================================================")
            return 0
        else:
            print("RESULTADO VALIDACIÓN: FAIL — Discrepancia detectada (ver detalles arriba).")
            print("=================================================================")
            return 1

    except Exception as exc:
        print(f"\nPRODUCTION VALIDATION: BLOCKED — Error connecting to database.")
        print(f"  Cause: {type(exc).__name__}: {exc}")
        print("  Note: Railway private PostgreSQL (postgres.railway.internal) is not")
        print("  directly reachable from the local development environment.")
        return 2


if __name__ == "__main__":
    sys.exit(validate_production())
