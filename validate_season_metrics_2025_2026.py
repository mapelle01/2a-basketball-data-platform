#!/usr/bin/env python3
"""FASE 23.4 — Production Read-Only Validator for Season Metrics.

Connects to PostgreSQL (via FEB_SCORE_DATABASE_URL or DATABASE_URL) in read-only
mode to validate the Season Metrics read model (SeasonPlayerMetrics /
SeasonTeamMetrics) for the 2025-2026 season:

  * Player metrics  – per-game values are consistent with totals
    (per_game x games_played == total, float tolerance), non-negative and
    finite; season isolation; deterministic ordering; SUM(games_played)
    matches the raw match_player_stats row count.
  * Team metrics    – per-game consistency (points_per_game x gp == points_for,
    points_against_per_game x gp == points_against,
    point_difference_per_game x gp == points_for - points_against,
    win_percentage == wins / gp x 100); season-wide invariants
    SUM(games_played) == 728, SUM(wins) == SUM(losses) == 364; season isolation.
  * Raw cross-check – metrics-derived totals vs direct SQL SUMs.

READ-ONLY: performs no INSERT/UPDATE/DELETE and prints no connection secrets.

Usage:
    FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_metrics_2025_2026.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath("src"))

from feb_score.application.use_cases.season_metrics_service import SeasonMetricsService
from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository


SEASON = "2025-2026"
EXPECTED_TEAM_GAMES = 728  # 364 matches x 2 equipos
EXPECTED_MATCHES = 364
EXPECTED_TEAMS = 28

_TOL = 1e-6  # float tolerance for per-game x games_played round-trips


def validate_production(season_code: str = SEASON) -> int:
    dsn = os.environ.get("FEB_SCORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: FEB_SCORE_DATABASE_URL / DATABASE_URL not set in environment.")
        return 1

    print("=================================================================")
    print(f"FASE 23.4 — Season Metrics Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        repo = PgMatchStatsRepository(db)
        svc = SeasonMetricsService(repo)

        failures: list[str] = []

        # ------------------------------------------------------------------
        # 1. Player metrics
        # ------------------------------------------------------------------
        player_metrics = list(svc.list_season_player_metrics(season_code))
        num_players = len(player_metrics)

        # season isolation + determinism
        bad_season_players = [m for m in player_metrics if m.season_code != season_code]
        player_ids = [m.player_external_id for m in player_metrics]
        ordered_players = player_ids == sorted(player_ids)
        dup_players = len(player_ids) != len(set(player_ids))

        pg_fields = ("points_per_game", "rebounds_per_game", "assists_per_game",
                     "steals_per_game", "blocks_per_game", "turnovers_per_game",
                     "minutes_per_game")
        player_inconsistent: list[str] = []
        for m in player_metrics:
            for f in pg_fields:
                v = getattr(m, f)
                if not math.isfinite(v) or v < 0:
                    player_inconsistent.append(f"{m.player_external_id}.{f}")
            # round-trip: per_game x games_played == total
            for total_f, pg_f in (("points", "points_per_game"), ("rebounds", "rebounds_per_game"),
                                  ("assists", "assists_per_game"), ("steals", "steals_per_game"),
                                  ("blocks", "blocks_per_game"), ("turnovers", "turnovers_per_game")):
                if abs(getattr(m, pg_f) * m.games_played - getattr(m, total_f)) > _TOL:
                    player_inconsistent.append(f"{m.player_external_id}.{pg_f}")
            if abs(m.minutes_per_game * m.games_played - m.minutes) > _TOL:
                player_inconsistent.append(f"{m.player_external_id}.minutes_per_game")

        sum_player_games = sum(m.games_played for m in player_metrics)
        sum_player_points = sum(m.points for m in player_metrics)
        sum_player_pg_points = sum(m.points_per_game * m.games_played for m in player_metrics)

        leaders = {}
        for metric in pg_fields:
            if player_metrics:
                leaders[metric] = max(player_metrics, key=lambda m: getattr(m, metric))

        print(f"\n1. Jugadores ({season_code}): {num_players}")
        print("   Líderes por métrica (media por partido):")
        for metric, m in leaders.items():
            print(f"     * {metric:<22}: Player {m.player_external_id}"
                  f" — {getattr(m, metric):.3f} ({m.games_played} PJ)")
        print(f"   SUM(games_played)        = {sum_player_games}")
        print(f"   SUM(points)              = {sum_player_points}")
        print(f"   SUM(points_per_game*gp)  = {sum_player_pg_points:.3f}")
        if bad_season_players:
            failures.append(f"player metrics from other seasons: {len(bad_season_players)}")
        if dup_players:
            failures.append("duplicate players in metrics")
        if not ordered_players:
            failures.append("player metrics not ordered by player_external_id")
        if player_inconsistent:
            failures.append(f"player per-game inconsistencies: {player_inconsistent[:5]}...")

        # raw cross-check
        conn = db.connect()
        try:
            raw_player = conn.execute(
                "SELECT COUNT(*) AS rows_n,"
                " COALESCE(SUM(points), 0) AS raw_points"
                " FROM match_player_stats WHERE season_code = %s",
                (season_code,),
            ).fetchone()
            raw_team = conn.execute(
                "SELECT COUNT(*) AS rows_n,"
                " COALESCE(SUM(points_for), 0) AS raw_pf,"
                " COALESCE(SUM(points_against), 0) AS raw_pa"
                " FROM match_team_stats WHERE season_code = %s",
                (season_code,),
            ).fetchone()
        finally:
            conn.close()

        if sum_player_games != raw_player["rows_n"]:
            failures.append(
                f"player SUM(games_played)={sum_player_games} != raw rows={raw_player['rows_n']}")
        if abs(sum_player_points - raw_player["raw_points"]) > _TOL:
            failures.append(
                f"player SUM(points)={sum_player_points} != raw SUM(points)={raw_player['raw_points']}")

        # ------------------------------------------------------------------
        # 2. Team metrics
        # ------------------------------------------------------------------
        team_metrics = list(svc.list_season_team_metrics(season_code))
        num_teams = len(team_metrics)

        bad_season_teams = [m for m in team_metrics if m.season_code != season_code]
        team_ids = [m.team_external_id for m in team_metrics]
        dup_teams = len(team_ids) != len(set(team_ids))

        sum_team_games = sum(m.games_played for m in team_metrics)
        sum_wins = sum(m.wins for m in team_metrics)
        sum_losses = sum(m.losses for m in team_metrics)
        sum_pf = sum(m.points_for for m in team_metrics)
        sum_pa = sum(m.points_against for m in team_metrics)

        team_inconsistent: list[str] = []
        for m in team_metrics:
            if abs(m.points_per_game * m.games_played - m.points_for) > _TOL:
                team_inconsistent.append(f"{m.team_external_id}.points_per_game")
            if abs(m.points_against_per_game * m.games_played - m.points_against) > _TOL:
                team_inconsistent.append(f"{m.team_external_id}.points_against_per_game")
            if abs(m.point_difference_per_game * m.games_played
                   - (m.points_for - m.points_against)) > _TOL:
                team_inconsistent.append(f"{m.team_external_id}.point_difference_per_game")
            expected_wp = (m.wins / m.games_played * 100.0) if m.games_played > 0 else 0.0
            if abs(m.win_percentage - expected_wp) > _TOL:
                team_inconsistent.append(f"{m.team_external_id}.win_percentage")
            for f in ("field_goals_made_per_game", "field_goals_attempted_per_game",
                      "three_points_made_per_game", "three_points_attempted_per_game",
                      "free_throws_made_per_game", "free_throws_attempted_per_game",
                      "turnovers_per_game", "rebounds_per_game"):
                if not math.isfinite(getattr(m, f)):
                    team_inconsistent.append(f"{m.team_external_id}.{f}")

        print(f"\n2. Equipos ({season_code}): {num_teams}  (esperado {EXPECTED_TEAMS})")
        print(f"   SUM(games_played) = {sum_team_games}  (esperado {EXPECTED_TEAM_GAMES})")
        print(f"   SUM(wins)         = {sum_wins}  (esperado {EXPECTED_MATCHES})")
        print(f"   SUM(losses)       = {sum_losses}  (esperado {EXPECTED_MATCHES})")
        print(f"   SUM(points_for)   = {sum_pf}  (raw: {raw_team['raw_pf']})")
        print(f"   SUM(points_agg)   = {sum_pa}  (raw: {raw_team['raw_pa']})")

        print("\n   Métricas por equipo (top por % victorias):")
        for m in sorted(team_metrics, key=lambda m: m.win_percentage, reverse=True):
            print(f"     {m.team_external_id:<12} {m.wins}W-{m.losses}L"
                  f"  PPG={m.points_per_game:.1f} PAPG={m.points_against_per_game:.1f}"
                  f" DIFF={m.point_difference_per_game:+.1f}  WIN%={m.win_percentage:.1f}")

        if bad_season_teams:
            failures.append(f"team metrics from other seasons: {len(bad_season_teams)}")
        if dup_teams:
            failures.append("duplicate teams in metrics")
        if num_teams != EXPECTED_TEAMS:
            failures.append(f"team count {num_teams} != {EXPECTED_TEAMS}")
        if sum_team_games != EXPECTED_TEAM_GAMES:
            failures.append(f"SUM(games_played)={sum_team_games} != {EXPECTED_TEAM_GAMES}")
        if sum_wins != EXPECTED_MATCHES:
            failures.append(f"SUM(wins)={sum_wins} != {EXPECTED_MATCHES}")
        if sum_losses != EXPECTED_MATCHES:
            failures.append(f"SUM(losses)={sum_losses} != {EXPECTED_MATCHES}")
        if abs(sum_pf - raw_team["raw_pf"]) > _TOL:
            failures.append(f"team SUM(points_for)={sum_pf} != raw={raw_team['raw_pf']}")
        if abs(sum_pa - raw_team["raw_pa"]) > _TOL:
            failures.append(f"team SUM(points_against)={sum_pa} != raw={raw_team['raw_pa']}")
        if team_inconsistent:
            failures.append(f"team per-game inconsistencies: {team_inconsistent[:5]}...")

        # ------------------------------------------------------------------
        # 3. Verdict
        # ------------------------------------------------------------------
        print("\n=================================================================")
        if not failures:
            print("RESULTADO VALIDACIÓN: PASS — Métricas de temporada consistentes e íntegras.")
            print("=================================================================")
            return 0
        print("RESULTADO VALIDACIÓN: FAIL — Discrepancias detectadas:")
        for f in failures:
            print(f"  - {f}")
        print("=================================================================")
        return 1

    except Exception as exc:  # noqa: BLE001 - READ-ONLY validator never leaks state
        print(f"\nPRODUCTION VALIDATION: BLOCKED — {type(exc).__name__}")
        print("  No connection secrets are printed.")
        print("  Note: Railway private PostgreSQL (postgres.railway.internal) is not")
        print("  directly reachable from the local development environment; use a")
        print("  `railway connect Postgres` tunnel if validating from the CLI.")
        return 2


if __name__ == "__main__":
    sys.exit(validate_production())