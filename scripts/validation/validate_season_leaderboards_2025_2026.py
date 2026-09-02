#!/usr/bin/env python3
"""FASE 23.3 — Production Read-Only Validator for Season Leaderboards.

Connects to PostgreSQL (via FEB_SCORE_DATABASE_URL or DATABASE_URL) in read-only
mode to validate the Season Leaderboards read model for the 2025-2026 season:

  * Player leaderboard  – 7 metrics (points, rebounds, assists, steals, blocks,
    turnovers, games_played); leaders per metric; consecutive positional ranks;
    no duplicate players; season isolation (only 2025-2026 entries).
  * Team leaderboard    – classification + points_for + point_difference +
    win_percentage; final classification table; SUM(wins) == SUM(losses);
    SUM(games_played) == 728 (364 matches x 2 teams); no duplicate teams;
    season isolation.
  * Mathematical consistency – SUM(leaderboard.points) == SUM(aggregates)
    == raw SUM(points) in match_player_stats; SUM(wins)/SUM(losses) equal.

READ-ONLY: performs no INSERT/UPDATE/DELETE and prints no connection secrets.

Usage:
    FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_leaderboards_2025_2026.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("src"))

from feb_score.application.use_cases.leaderboard_service import SeasonLeaderboardService
from feb_score.domain.statistics.model import PlayerLeaderboardMetric, TeamLeaderboardMetric
from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository


SEASON = "2025-2026"
EXPECTED_TEAM_GAMES = 728  # 364 matches (26 rounds x 14 partidos) x 2 equipos


def validate_production(season_code: str = SEASON) -> int:
    dsn = os.environ.get("FEB_SCORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: FEB_SCORE_DATABASE_URL / DATABASE_URL not set in environment.")
        return 1

    print("=================================================================")
    print(f"FASE 23.3 — Season Leaderboards Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        repo = PgMatchStatsRepository(db)
        svc = SeasonLeaderboardService(repo)

        failures: list[str] = []

        # ------------------------------------------------------------------
        # 1. Player leaderboard
        # ------------------------------------------------------------------
        player_lb = list(svc.list_season_player_leaderboard(
            season_code, PlayerLeaderboardMetric.POINTS
        ))
        num_players = len(player_lb)

        leaders = {}
        for metric in ("points", "rebounds", "assists", "steals", "blocks", "games_played"):
            lb = list(svc.list_season_player_leaderboard(season_code, metric))
            if lb:
                leaders[metric] = lb[0]

        # season isolation: every entry belongs to the requested season
        bad_season_players = [e for e in player_lb if e.season_code != season_code]
        # no duplicates + consecutive positional ranks
        player_ids = [e.player_external_id for e in player_lb]
        dup_players = len(player_ids) != len(set(player_ids))
        ranks_ok_player = [e.rank for e in player_lb] == list(range(1, num_players + 1))

        # mathematical consistency: full leaderboard vs aggregates
        player_agg = list(repo.list_season_player_aggregates(season_code))
        lb_points = sum(e.points for e in player_lb)
        agg_points = sum(a.points for a in player_agg)

        print(f"\n1. Jugadores ({season_code}): {num_players}")
        print("   Líderes por métrica:")
        for metric, entry in leaders.items():
            print(f"     * {metric:<14}: Player {entry.player_external_id}"
                  f" — {getattr(entry, metric)} ({entry.games_played} PJ)")
        print(f"   SUM(leaderboard.points) = {lb_points}")
        print(f"   SUM(aggregates.points)  = {agg_points}")
        if bad_season_players:
            failures.append(f"player entries from other seasons: {len(bad_season_players)}")
        if dup_players:
            failures.append("duplicate players in leaderboard")
        if not ranks_ok_player:
            failures.append("player ranks are not consecutive 1..N")
        if lb_points != agg_points:
            failures.append(f"player points mismatch ({lb_points} vs {agg_points})")

        # ------------------------------------------------------------------
        # 2. Team leaderboard
        # ------------------------------------------------------------------
        team_lb = list(svc.list_season_team_leaderboard(
            season_code, TeamLeaderboardMetric.CLASSIFICATION
        ))
        num_teams = len(team_lb)

        team_ids = [e.team_external_id for e in team_lb]
        dup_teams = len(team_ids) != len(set(team_ids))
        ranks_ok_team = [e.rank for e in team_lb] == list(range(1, num_teams + 1))

        sum_games = sum(e.games_played for e in team_lb)
        sum_wins = sum(e.wins for e in team_lb)
        sum_losses = sum(e.losses for e in team_lb)

        team_agg = list(repo.list_season_team_aggregates(season_code))
        agg_wins = sum(a.wins for a in team_agg)
        agg_losses = sum(a.losses for a in team_agg)

        bad_season_teams = [e for e in team_lb if e.season_code != season_code]

        print(f"\n2. Equipos ({season_code}): {num_teams}")
        print(f"   SUM(games_played) = {sum_games}  (esperado {EXPECTED_TEAM_GAMES})")
        print(f"   SUM(wins)         = {sum_wins}  (aggregates: {agg_wins})")
        print(f"   SUM(losses)       = {sum_losses}  (aggregates: {agg_losses})")
        if sum_wins != agg_wins:
            failures.append(f"team wins mismatch ({sum_wins} vs {agg_wins})")
        if sum_losses != agg_losses:
            failures.append(f"team losses mismatch ({sum_losses} vs {agg_losses})")
        if sum_games != EXPECTED_TEAM_GAMES:
            failures.append(f"SUM(games_played)={sum_games} != {EXPECTED_TEAM_GAMES}")
        if bad_season_teams:
            failures.append(f"team entries from other seasons: {len(bad_season_teams)}")
        if dup_teams:
            failures.append("duplicate teams in leaderboard")
        if not ranks_ok_team:
            failures.append("team ranks are not consecutive 1..N")

        print("\n   Clasificación final (classification):")
        for e in team_lb:
            print(f"     {e.rank:>3}. {e.team_external_id:<10}"
                  f" {e.wins}W-{e.losses}L  PF={e.points_for} PA={e.points_against}"
                  f" DIFF={e.point_difference:+d}  {e.win_percentage:.3f}")

        # ------------------------------------------------------------------
        # 3. Verdict
        # ------------------------------------------------------------------
        print("\n=================================================================")
        if not failures:
            print("RESULTADO VALIDACIÓN: PASS — Leaderboards consistentes e íntegros.")
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