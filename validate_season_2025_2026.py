#!/usr/bin/env python3
"""FASE 23.1 — Production Read-Only Validator for Season Player Aggregates.

Connects to PostgreSQL (via FEB_SCORE_DATABASE_URL or DATABASE_URL) in read-only
mode to compute and assert the mathematical consistency of season player aggregates.
Never prints connection secrets or modifies any state.
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
    print(f"FASE 23.1 — Season Player Aggregates Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        repo = PgMatchStatsRepository(db)

        # 1. Fetch domain aggregates via repository
        aggregates = list(repo.list_season_player_aggregates(season_code))
        num_players = len(aggregates)

        aggr_games = sum(a.games_played for a in aggregates)
        aggr_points = sum(a.points for a in aggregates)
        aggr_rebounds = sum(a.rebounds for a in aggregates)
        aggr_assists = sum(a.assists for a in aggregates)
        aggr_steals = sum(a.steals for a in aggregates)
        aggr_blocks = sum(a.blocks for a in aggregates)
        aggr_turnovers = sum(a.turnovers for a in aggregates)
        aggr_minutes = sum(a.minutes for a in aggregates)

        # 2. Query direct totals from raw match_player_stats table for the season
        conn = db.connect()
        try:
            # Check match count for season
            row_matches = conn.execute(
                "SELECT COUNT(DISTINCT external_id) AS cnt FROM matches WHERE season_code = %s",
                (season_code,),
            ).fetchone()
            num_matches = row_matches["cnt"] if row_matches else 0

            # Raw sums for season
            row_stats = conn.execute(
                "SELECT "
                "  COUNT(*) AS total_rows, "
                "  COUNT(DISTINCT player_external_id) AS total_distinct_players, "
                "  COALESCE(SUM(points), 0) AS raw_points, "
                "  COALESCE(SUM(rebounds), 0) AS raw_rebounds, "
                "  COALESCE(SUM(assists), 0) AS raw_assists, "
                "  COALESCE(SUM(steals), 0) AS raw_steals, "
                "  COALESCE(SUM(blocks), 0) AS raw_blocks, "
                "  COALESCE(SUM(turnovers), 0) AS raw_turnovers, "
                "  COALESCE(SUM(minutes), 0.0) AS raw_minutes "
                "FROM match_player_stats "
                "WHERE season_code = %s",
                (season_code,),
            ).fetchone()

            # Isolation check: other seasons
            row_other = conn.execute(
                "SELECT COUNT(*) AS other_cnt FROM match_player_stats WHERE season_code != %s",
                (season_code,),
            ).fetchone()
            other_season_rows = row_other["other_cnt"] if row_other else 0

        finally:
            conn.close()

        raw_rows = row_stats["total_rows"]
        raw_distinct_players = row_stats["total_distinct_players"]
        raw_points = row_stats["raw_points"]
        raw_rebounds = row_stats["raw_rebounds"]
        raw_assists = row_stats["raw_assists"]
        raw_steals = row_stats["raw_steals"]
        raw_blocks = row_stats["raw_blocks"]
        raw_turnovers = row_stats["raw_turnovers"]
        raw_minutes = float(row_stats["raw_minutes"])

        print(f"\n1. Partidos persistidos ({season_code}): {num_matches}")
        print(f"2. Jugadores agregados ({season_code}):   {num_players} (raw distinct: {raw_distinct_players})")
        print(f"3. Filas totales match_player_stats:     {raw_rows}")
        print(f"4. Filas otras temporadas (aislamiento): {other_season_rows}")

        print("\n--- Métricas Agregadas vs Tabla Raw ---")
        metrics = [
            ("points", aggr_points, raw_points),
            ("rebounds", aggr_rebounds, raw_rebounds),
            ("assists", aggr_assists, raw_assists),
            ("steals", aggr_steals, raw_steals),
            ("blocks", aggr_blocks, raw_blocks),
            ("turnovers", aggr_turnovers, raw_turnovers),
            ("minutes", round(aggr_minutes, 2), round(raw_minutes, 2)),
            ("games_played sum", aggr_games, raw_rows),
        ]

        all_match = True
        for name, aggr_val, raw_val in metrics:
            matched = aggr_val == raw_val
            if not matched:
                all_match = False
            status_str = "MATCH" if matched else "MISMATCH"
            print(f"  * {name:<18}: Aggregated = {aggr_val:<10} | Raw = {raw_val:<10} [{status_str}]")

        if aggregates:
            top_scorer = max(aggregates, key=lambda a: a.points)
            most_games = max(aggregates, key=lambda a: a.games_played)
            top_rebounder = max(aggregates, key=lambda a: a.rebounds)
            top_assister = max(aggregates, key=lambda a: a.assists)

            print("\n--- Líderes Estadísticos de Temporada ---")
            print(f"  * Máximo anotador : Player {top_scorer.player_external_id} con {top_scorer.points} puntos ({top_scorer.games_played} PJ)")
            print(f"  * Más partidos    : Player {most_games.player_external_id} con {most_games.games_played} partidos")
            print(f"  * Máximo reboteador: Player {top_rebounder.player_external_id} con {top_rebounder.rebounds} rebotes")
            print(f"  * Máximo asistente : Player {top_assister.player_external_id} con {top_assister.assists} asistencias")

        print("\n=================================================================")
        if all_match and num_players == raw_distinct_players:
            print("RESULTADO VALIDACIÓN: PASS — Consistencia matemática e integridad verificadas al 100%.")
            print("=================================================================")
            return 0
        else:
            print("RESULTADO VALIDACIÓN: FAIL — Discrepancia matemática detectada.")
            print("=================================================================")
            return 1

    except Exception as exc:
        print(f"\nPRODUCTION VALIDATION: BLOCKED — Error connecting to database: {exc}")
        print("Note: Railway private PostgreSQL might not be directly reachable from local environment.")
        return 2


if __name__ == "__main__":
    sys.exit(validate_production())
