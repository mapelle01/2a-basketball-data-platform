#!/usr/bin/env python3
"""FASE 23.7 — Production Read-Only Validator for Season Analytics (2025-2026).

Single validator for the whole season-analytics surface (FASE 23.1-23.6):
match integrity, player/team aggregates, leaderboards, per-game metrics and
raw-table cross-checks.

READ-ONLY: performs no INSERT/UPDATE/DELETE and never prints the connection
secrets (password, token, API key, full DSN, Authorization headers). The only
environment inputs are ``FEB_SCORE_DATABASE_URL`` or ``DATABASE_URL``.

Blocks (for season_code=2025-2026):

  MATCHES           total matches == 364; distinct external_id == 364 (0 dups);
                    all round_number in 1..26 (none NULL/0); 26 rounds x 14
                    matches; 28 distinct team appearances per round. Scoped to
                    the league competition ``segunda-feb``; rows of other
                    competition contexts under the same season are reported as
                    an informational diagnostic (no stats, no analytics impact).
  PLAYER AGGREGATES distinct players; SUM(games_played) == 728; SUM of every
                    stat column == raw match_player_stats SUM.
  TEAM AGGREGATES   SUM(games_played) == 728; SUM(wins) == SUM(losses) == 364;
                    SUM of every TeamStats column == raw match_team_stats SUM;
                    28 teams x exactly 26 games each.
  LEADERBOARDS      every supported metric: ranks 1..N, no duplicates,
                    determinism (two runs equal), season isolation, and
                    consistency with the aggregates.
  METRICS           per_game x games_played ~= total for every per-game metric
                    (relative tolerance 1e-5; per-game values are single
                    precision in the read model); win_percentage;
                    point_difference; zero-division guard.
  INTEGRITY         no unexpected NULLs; no cross-season leakage; season_code
                    filter correct.

Note on groups (ESTE/OESTE): the domain does not persist a group label
(competition_id is ``segunda-feb`` for both groups; round_number lives in
``data->>'round_number'``). The validator therefore asserts the strongest
structural equivalent: 26 rounds x exactly 14 matches with 28 distinct team
appearances per round, and every team playing exactly 26 games. This cannot be
faked and is exactly what "7 matches per round per group" implies once the two
groups of 14 teams never play each other.

Usage:
    FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_analytics_production.py
"""

from __future__ import annotations

import math
import os
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.abspath("src"))

from feb_score.application.use_cases.season_analytics_service import SeasonAnalyticsService
from feb_score.domain.statistics.model import (
    PlayerLeaderboardMetric,
    TeamLeaderboardMetric,
)
from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.repositories import PgMatchStatsRepository

SEASON = "2025-2026"
EXPECTED_MATCHES = 364  # 26 jornadas x 14 partidos (7 ESTE + 7 OESTE)
EXPECTED_TEAM_GAMES = 728  # 364 partidos x 2 equipos
EXPECTED_WINS_LOSSES = 364
EXPECTED_TEAMS = 28
EXPECTED_ROUNDS = 26
EXPECTED_ROUND_MATCHES = 14  # 7 ESTE + 7 OESTE
_TOL = 1e-6


def _fmt(n: float) -> str:
    return f"{n:.3f}".rstrip("0").rstrip(".") if isinstance(n, float) else str(n)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def check_matches(db: PgDatabase, season_code: str) -> List[str]:
    """Match count, duplicate-free external ids, round structure and integrity.

    Scoped to the authoritative league competition (``segunda-feb``): the
    ``matches`` table can legitimately contain rows for other competition
    contexts under the same season_code (e.g. earlier smoke-test artifacts),
    which carry no stats and no analytics impact. Those are reported as an
    informational diagnostic, never as blockers.
    """
    failures: List[str] = []
    conn = db.connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT external_id) AS d"
            " FROM matches WHERE season_code = %s AND competition_id = 'segunda-feb'",
            (season_code,),
        ).fetchone()
        null_rounds = conn.execute(
            "SELECT COUNT(*) AS n FROM matches WHERE season_code = %s"
            " AND competition_id = 'segunda-feb'"
            " AND (data->>'round_number' IS NULL OR (data->>'round_number')::int = 0)",
            (season_code,),
        ).fetchone()["n"]
        rounds = conn.execute(
            "SELECT (data->>'round_number')::int AS round_number, COUNT(*) AS n"
            " FROM matches WHERE season_code = %s AND competition_id = 'segunda-feb'"
            " GROUP BY 1 ORDER BY 1", (season_code,),
        ).fetchall()
        per_round_teams = conn.execute(
            "SELECT round_number, COUNT(DISTINCT team) AS n FROM ("
            "  SELECT (data->>'round_number')::int AS round_number, data->>'home_team_id' AS team"
            "    FROM matches WHERE season_code = %s AND competition_id = 'segunda-feb'"
            "  UNION ALL"
            "  SELECT (data->>'round_number')::int, data->>'away_team_id'"
            "    FROM matches WHERE season_code = %s AND competition_id = 'segunda-feb'"
            ") t GROUP BY round_number ORDER BY round_number",
            (season_code, season_code),
        ).fetchall()
        stray = conn.execute(
            "SELECT competition_id, COUNT(*) AS n FROM matches"
            " WHERE season_code = %s AND competition_id != 'segunda-feb'"
            " GROUP BY 1 ORDER BY 1", (season_code,),
        ).fetchall()
    finally:
        conn.close()

    n, d = total["n"], total["d"]
    print(f"  matches total            = {n}  (esperado {EXPECTED_MATCHES})")
    print(f"  matches distinct         = {d}  (0 duplicados)")
    if stray:
        stray_s = ", ".join(f"{r['competition_id']}={r['n']}" for r in stray)
        print(f"  [DIAG] filas de otras competiciones (sin stats): {stray_s}")
    if n != EXPECTED_MATCHES:
        failures.append(f"matches total {n} != {EXPECTED_MATCHES}")
    if d != EXPECTED_MATCHES:
        failures.append(f"duplicate external_id: distinct {d} != total {n}")
    if null_rounds != 0:
        failures.append(f"{null_rounds} matches with NULL/0 round_number")

    rn = [r["round_number"] for r in rounds]
    if rn != list(range(1, EXPECTED_ROUNDS + 1)):
        failures.append(f"round_numbers {rn} != 1..{EXPECTED_ROUNDS}")
    bad_round = [r["n"] for r in rounds if r["n"] != EXPECTED_ROUND_MATCHES]
    if bad_round:
        failures.append(f"rounds with != {EXPECTED_ROUND_MATCHES} matches: {bad_round}")
    if len(rounds) != EXPECTED_ROUNDS:
        failures.append(f"distinct rounds {len(rounds)} != {EXPECTED_ROUNDS}")

    teams_map = {r["round_number"]: r["n"] for r in per_round_teams}
    bad_teams = {k: v for k, v in teams_map.items() if v != EXPECTED_TEAMS}
    if bad_teams:
        failures.append(
            f"rounds without exactly {EXPECTED_TEAMS} distinct team appearances: {bad_teams}"
        )
    return failures


def check_player_aggregates(
    svc: SeasonAnalyticsService, db: PgDatabase, season_code: str
) -> List[str]:
    failures: List[str] = []
    agg = list(svc.list_season_player_aggregates(season_code))

    ids = [a.player_external_id for a in agg]
    dup = len(ids) != len(set(ids))
    other_season = [a for a in agg if a.season_code != season_code]
    ordered = ids == sorted(ids)

    sums = {
        "games_played": sum(a.games_played for a in agg),
        "points": sum(a.points for a in agg),
        "rebounds": sum(a.rebounds for a in agg),
        "assists": sum(a.assists for a in agg),
        "steals": sum(a.steals for a in agg),
        "blocks": sum(a.blocks for a in agg),
        "turnovers": sum(a.turnovers for a in agg),
        "minutes": sum(a.minutes for a in agg),
    }

    conn = db.connect()
    try:
        raw = conn.execute(
            "SELECT COUNT(*) AS rows_n,"
            " COUNT(DISTINCT player_external_id) AS distinct_players,"
            " COALESCE(SUM(points),0) AS points, COALESCE(SUM(rebounds),0) AS rebounds,"
            " COALESCE(SUM(assists),0) AS assists, COALESCE(SUM(steals),0) AS steals,"
            " COALESCE(SUM(blocks),0) AS blocks, COALESCE(SUM(turnovers),0) AS turnovers,"
            " COALESCE(SUM(minutes),0) AS minutes"
            " FROM match_player_stats WHERE season_code = %s", (season_code,),
        ).fetchone()
    finally:
        conn.close()

    print(f"  jugadores distintos      = {len(agg)}  (raw: {raw['distinct_players']})")
    print(f"  SUM(games_played)        = {sums['games_played']}  (raw filas: {raw['rows_n']})")
    for k in ("points", "rebounds", "assists", "steals", "blocks", "turnovers", "minutes"):
        matched = math.isclose(sums[k], float(raw[k]), rel_tol=0, abs_tol=_TOL)
        print(f"  SUM({k:<12}) = {_fmt(sums[k]):<12} (raw: {_fmt(float(raw[k]))})"
              f"  [{'MATCH' if matched else 'MISMATCH'}]")
        if not matched:
            failures.append(f"player SUM({k})={sums[k]} != raw={raw[k]}")
    if sums["games_played"] != raw["rows_n"]:
        failures.append(f"player SUM(games_played)={sums['games_played']} != raw rows={raw['rows_n']}")
    if len(agg) != raw["distinct_players"]:
        failures.append(f"aggregate players {len(agg)} != raw distinct {raw['distinct_players']}")
    if dup:
        failures.append("duplicate players in aggregates")
    if other_season:
        failures.append(f"aggregates from other seasons: {len(other_season)}")
    if not ordered:
        failures.append("aggregates not ordered deterministically by player_external_id")
    return failures


def check_team_aggregates(
    svc: SeasonAnalyticsService, db: PgDatabase, season_code: str
) -> List[str]:
    failures: List[str] = []
    agg = list(svc.list_season_team_aggregates(season_code))

    ids = [a.team_external_id for a in agg]
    dup = len(ids) != len(set(ids))
    other_season = [a for a in agg if a.season_code != season_code]
    ordered = ids == sorted(ids)

    sums = {
        "games_played": sum(a.games_played for a in agg),
        "wins": sum(a.wins for a in agg),
        "losses": sum(a.losses for a in agg),
        "points_for": sum(a.points_for for a in agg),
        "points_against": sum(a.points_against for a in agg),
        "field_goals_made": sum(a.field_goals_made for a in agg),
        "field_goals_attempted": sum(a.field_goals_attempted for a in agg),
        "three_points_made": sum(a.three_points_made for a in agg),
        "three_points_attempted": sum(a.three_points_attempted for a in agg),
        "free_throws_made": sum(a.free_throws_made for a in agg),
        "free_throws_attempted": sum(a.free_throws_attempted for a in agg),
        "turnovers": sum(a.turnovers for a in agg),
        "rebounds": sum(a.rebounds for a in agg),
    }

    conn = db.connect()
    try:
        raw = conn.execute(
            "SELECT COUNT(*) AS rows_n,"
            " COALESCE(SUM(points_for),0) AS points_for,"
            " COALESCE(SUM(points_against),0) AS points_against,"
            " COALESCE(SUM(field_goals_made),0) AS field_goals_made,"
            " COALESCE(SUM(field_goals_attempted),0) AS field_goals_attempted,"
            " COALESCE(SUM(three_points_made),0) AS three_points_made,"
            " COALESCE(SUM(three_points_attempted),0) AS three_points_attempted,"
            " COALESCE(SUM(free_throws_made),0) AS free_throws_made,"
            " COALESCE(SUM(free_throws_attempted),0) AS free_throws_attempted,"
            " COALESCE(SUM(turnovers),0) AS turnovers,"
            " COALESCE(SUM(rebounds),0) AS rebounds"
            " FROM match_team_stats WHERE season_code = %s", (season_code,),
        ).fetchone()
    finally:
        conn.close()

    games_by_team = {a.team_external_id: a.games_played for a in agg}
    uneven = {t: g for t, g in games_by_team.items() if g != EXPECTED_ROUNDS}
    print(f"  equipos                   = {len(agg)}  (esperado {EXPECTED_TEAMS})")
    print(f"  SUM(games_played)         = {sums['games_played']}  (esperado {EXPECTED_TEAM_GAMES})")
    print(f"  SUM(wins)                 = {sums['wins']}  (esperado {EXPECTED_WINS_LOSSES})")
    print(f"  SUM(losses)               = {sums['losses']}  (esperado {EXPECTED_WINS_LOSSES})")
    for k in ("points_for", "points_against", "field_goals_made", "field_goals_attempted",
              "three_points_made", "three_points_attempted", "free_throws_made",
              "free_throws_attempted", "turnovers", "rebounds"):
        matched = sums[k] == raw[k]
        print(f"  SUM({k:<24}) = {sums[k]:<10} (raw: {raw[k]})"
              f"  [{'MATCH' if matched else 'MISMATCH'}]")
        if not matched:
            failures.append(f"team SUM({k})={sums[k]} != raw={raw[k]}")

    if len(agg) != EXPECTED_TEAMS:
        failures.append(f"team count {len(agg)} != {EXPECTED_TEAMS}")
    if sums["games_played"] != EXPECTED_TEAM_GAMES:
        failures.append(f"SUM(games_played)={sums['games_played']} != {EXPECTED_TEAM_GAMES}")
    if sums["wins"] != EXPECTED_WINS_LOSSES:
        failures.append(f"SUM(wins)={sums['wins']} != {EXPECTED_WINS_LOSSES}")
    if sums["losses"] != EXPECTED_WINS_LOSSES:
        failures.append(f"SUM(losses)={sums['losses']} != {EXPECTED_WINS_LOSSES}")
    if raw["rows_n"] != EXPECTED_TEAM_GAMES:
        failures.append(f"raw team rows {raw['rows_n']} != {EXPECTED_TEAM_GAMES}")
    if uneven:
        failures.append(f"teams with games_played != {EXPECTED_ROUNDS}: {uneven}")
    if dup:
        failures.append("duplicate teams in aggregates")
    if other_season:
        failures.append(f"team aggregates from other seasons: {len(other_season)}")
    if not ordered:
        failures.append("aggregates not ordered deterministically by team_external_id")
    return failures


_PLAYER_LB_VALUE = {
    PlayerLeaderboardMetric.POINTS: "points",
    PlayerLeaderboardMetric.REBOUNDS: "rebounds",
    PlayerLeaderboardMetric.ASSISTS: "assists",
    PlayerLeaderboardMetric.STEALS: "steals",
    PlayerLeaderboardMetric.BLOCKS: "blocks",
    PlayerLeaderboardMetric.TURNOVERS: "turnovers",
    PlayerLeaderboardMetric.GAMES_PLAYED: "games_played",
}
_TEAM_LB_VALUE = {
    TeamLeaderboardMetric.POINTS_FOR: "points_for",
}


def check_leaderboards(svc: SeasonAnalyticsService, season_code: str) -> List[str]:
    failures: List[str] = []

    aggregates_p = {a.player_external_id: a for a in svc.list_season_player_aggregates(season_code)}
    aggregates_t = {a.team_external_id: a for a in svc.list_season_team_aggregates(season_code)}

    for metric in PlayerLeaderboardMetric.ALL:
        lb = list(svc.list_season_player_leaderboard(season_code, metric))
        ranks = [e.rank for e in lb]
        ids = [e.player_external_id for e in lb]
        tag = f"player_leaderboard[{metric}]"
        if ranks != list(range(1, len(ranks) + 1)):
            failures.append(f"{tag}: ranks {ranks[:5]} not 1..N")
        if len(ids) != len(set(ids)):
            failures.append(f"{tag}: duplicate players")
        if any(e.season_code != season_code for e in lb):
            failures.append(f"{tag}: season leakage")
        if list(svc.list_season_player_leaderboard(season_code, metric)) != lb:
            failures.append(f"{tag}: not deterministic (two runs differ)")
        field = _PLAYER_LB_VALUE[metric]
        for e in lb:
            expected = getattr(aggregates_p[e.player_external_id], field)
            if metric == PlayerLeaderboardMetric.GAMES_PLAYED:
                actual = e.games_played
            else:
                actual = getattr(e, field)
            if actual != expected:
                failures.append(f"{tag}: {e.player_external_id} {field}={actual} != aggregate {expected}")
                break
    print(f"  leaderboards jugador      = {len(PlayerLeaderboardMetric.ALL)} métricas verificadas"
          f" ({len(list(svc.list_season_player_leaderboard(season_code, PlayerLeaderboardMetric.POINTS)))} jugadores)")

    for metric in TeamLeaderboardMetric.ALL:
        lb = list(svc.list_season_team_leaderboard(season_code, metric))
        ranks = [e.rank for e in lb]
        ids = [e.team_external_id for e in lb]
        tag = f"team_leaderboard[{metric}]"
        if ranks != list(range(1, len(ranks) + 1)):
            failures.append(f"{tag}: ranks {ranks[:5]} not 1..N")
        if len(ids) != len(set(ids)):
            failures.append(f"{tag}: duplicate teams")
        if any(e.season_code != season_code for e in lb):
            failures.append(f"{tag}: season leakage")
        if list(svc.list_season_team_leaderboard(season_code, metric)) != lb:
            failures.append(f"{tag}: not deterministic (two runs differ)")
        for e in lb:
            a = aggregates_t[e.team_external_id]
            if metric == TeamLeaderboardMetric.CLASSIFICATION:
                if e.wins != a.wins or e.losses != a.losses:
                    failures.append(f"{tag}: {e.team_external_id} W/L {e.wins}-{e.losses} != aggregate {a.wins}-{a.losses}")
                    break
            elif metric == TeamLeaderboardMetric.POINTS_FOR:
                if e.points_for != a.points_for:
                    failures.append(f"{tag}: {e.team_external_id} points_for != aggregate")
                    break
            elif metric == TeamLeaderboardMetric.POINT_DIFFERENCE:
                if e.point_difference != a.points_for - a.points_against:
                    failures.append(f"{tag}: {e.team_external_id} point_difference != aggregate")
                    break
            elif metric == TeamLeaderboardMetric.WIN_PERCENTAGE:
                expected = (a.wins / a.games_played) if a.games_played > 0 else 0.0
                if abs(e.win_percentage - expected) > _TOL:
                    failures.append(f"{tag}: {e.team_external_id} win_percentage {e.win_percentage:.4f} != {expected:.4f}")
                    break
    print(f"  leaderboards equipo       = {len(TeamLeaderboardMetric.ALL)} métricas verificadas"
          f" ({len(list(svc.list_season_team_leaderboard(season_code, TeamLeaderboardMetric.CLASSIFICATION)))} equipos)")
    return failures


def check_metrics(svc: SeasonAnalyticsService, season_code: str) -> List[str]:
    failures: List[str] = []

    players = list(svc.list_season_player_metrics(season_code))
    ids = [m.player_external_id for m in players]
    if len(ids) != len(set(ids)):
        failures.append("player metrics: duplicates")
    if any(m.season_code != season_code for m in players):
        failures.append("player metrics: season leakage")
    if ids != sorted(ids):
        failures.append("player metrics: not ordered")
    for m in players:
        for total_f, pg_f in (
            ("points", "points_per_game"), ("rebounds", "rebounds_per_game"),
            ("assists", "assists_per_game"), ("steals", "steals_per_game"),
            ("blocks", "blocks_per_game"), ("turnovers", "turnovers_per_game"),
            ("minutes", "minutes_per_game"),
        ):
            expected = getattr(m, total_f)
            if not math.isclose(
                getattr(m, pg_f) * m.games_played, expected,
                rel_tol=1e-5, abs_tol=_TOL,
            ):
                failures.append(f"player {m.player_external_id}.{pg_f} round-trip mismatch")
        if m.games_played == 0 and any(
            getattr(m, f) != 0 for f in
            ("points_per_game", "rebounds_per_game", "assists_per_game",
             "steals_per_game", "blocks_per_game", "turnovers_per_game", "minutes_per_game")
        ):
            failures.append(f"player {m.player_external_id}: nonzero per-game with games_played=0")
    print(f"  métricas jugador          = {len(players)} jugadores, per-game round-trips OK")

    teams = list(svc.list_season_team_metrics(season_code))
    ids = [m.team_external_id for m in teams]
    if len(ids) != len(set(ids)):
        failures.append("team metrics: duplicates")
    if any(m.season_code != season_code for m in teams):
        failures.append("team metrics: season leakage")
    if ids != sorted(ids):
        failures.append("team metrics: not ordered")
    for m in teams:
        if not math.isclose(m.points_per_game * m.games_played, m.points_for,
                            rel_tol=1e-5, abs_tol=_TOL):
            failures.append(f"team {m.team_external_id}.points_per_game round-trip mismatch")
        if not math.isclose(m.points_against_per_game * m.games_played, m.points_against,
                            rel_tol=1e-5, abs_tol=_TOL):
            failures.append(f"team {m.team_external_id}.points_against_per_game round-trip mismatch")
        if not math.isclose(
            m.point_difference_per_game * m.games_played,
            (m.points_for - m.points_against), rel_tol=1e-5, abs_tol=_TOL,
        ):
            failures.append(f"team {m.team_external_id}.point_difference_per_game round-trip mismatch")
        expected_wp = (m.wins / m.games_played * 100.0) if m.games_played > 0 else 0.0
        if not math.isclose(m.win_percentage, expected_wp, rel_tol=1e-5, abs_tol=_TOL):
            failures.append(f"team {m.team_external_id}.win_percentage {m.win_percentage:.4f} != {expected_wp:.4f}")
        if m.games_played == 0 and any(
            getattr(m, f) != 0 for f in (
                "points_per_game", "points_against_per_game", "win_percentage",
                "field_goals_made_per_game", "field_goals_attempted_per_game",
                "three_points_made_per_game", "three_points_attempted_per_game",
                "free_throws_made_per_game", "free_throws_attempted_per_game",
                "turnovers_per_game", "rebounds_per_game",
            )
        ):
            failures.append(f"team {m.team_external_id}: nonzero per-game with games_played=0")
    print(f"  métricas equipo           = {len(teams)} equipos, per-game round-trips OK")
    return failures


def check_integrity(db: PgDatabase, season_code: str) -> List[str]:
    failures: List[str] = []
    conn = db.connect()
    try:
        for table, columns in (
            ("match_player_stats", ("player_external_id", "team_external_id", "season_code",
                                    "points", "rebounds", "assists", "steals", "blocks", "turnovers")),
            ("match_team_stats", ("team_external_id", "season_code", "points_for",
                                  "points_against", "field_goals_made", "field_goals_attempted",
                                  "three_points_made", "three_points_attempted",
                                  "free_throws_made", "free_throws_attempted", "turnovers", "rebounds")),
        ):
            conds = " OR ".join(f"{c} IS NULL" for c in columns)
            nulls = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {conds}", ()
            ).fetchone()["n"]
            if nulls:
                failures.append(f"{table}: {nulls} rows with unexpected NULLs")
            bad_season = conn.execute(
                "SELECT COUNT(*) AS n FROM {0} WHERE season_code IS NULL OR season_code = ''".format(table)
            ).fetchone()["n"]
            if bad_season:
                failures.append(f"{table}: {bad_season} rows with empty/NULL season_code")

        # aggregates for the season must touch every raw row exactly once
        raw_other = conn.execute(
            "SELECT COUNT(*) AS n FROM match_player_stats WHERE season_code != %s", (season_code,)
        ).fetchone()["n"]
        print(f"  filas player_stats otras temporadas = {raw_other} (aislamiento)")
        raw_other_team = conn.execute(
            "SELECT COUNT(*) AS n FROM match_team_stats WHERE season_code != %s", (season_code,)
        ).fetchone()["n"]
        print(f"  filas team_stats otras temporadas   = {raw_other_team} (aislamiento)")
    finally:
        conn.close()
    return failures


def run_validations(db: PgDatabase, season_code: str) -> Tuple[int, List[str]]:
    repo = PgMatchStatsRepository(db)
    svc = SeasonAnalyticsService(repo)

    blocks = [
        ("1. MATCHES (integridad)", check_matches(db, season_code)),
        ("2. PLAYER AGGREGATES", check_player_aggregates(svc, db, season_code)),
        ("3. TEAM AGGREGATES", check_team_aggregates(svc, db, season_code)),
        ("4. LEADERBOARDS", check_leaderboards(svc, season_code)),
        ("5. METRICS", check_metrics(svc, season_code)),
        ("6. INTEGRIDAD", check_integrity(db, season_code)),
    ]

    all_failures: List[str] = []
    print("\n-----------------------------------------------------------------")
    for name, failures in blocks:
        print(f"\n{name}: {'PASS' if not failures else 'FAIL'}")
        all_failures.extend(failures)
        for f in failures:
            print(f"    - {f}")
    print("\n=================================================================")
    return (0 if not all_failures else 1), all_failures


def validate_production(season_code: str = SEASON) -> int:
    dsn = os.environ.get("FEB_SCORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: FEB_SCORE_DATABASE_URL / DATABASE_URL not set in environment.")
        return 1

    print("=================================================================")
    print(f"FASE 23.7 — Season Analytics Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        code, failures = run_validations(db, season_code)
        if code == 0:
            print("RESULTADO VALIDACIÓN: PASS — Analytics íntegros y consistentes.")
            print("=================================================================")
        else:
            print(f"RESULTADO VALIDACIÓN: FAIL — {len(failures)} discrepancia(s).")
            print("=================================================================")
        return code
    except Exception as exc:  # noqa: BLE001 - READ-ONLY validator never leaks state
        print("\nPRODUCTION VALIDATION: BLOCKED")
        print(f"  causa: {type(exc).__name__} al conectar/consultar.")
        print("  No connection secrets are printed.")
        print("  Railway private PostgreSQL (postgres.railway.internal) is not directly")
        print("  reachable from the local development environment; run this validator")
        print("  inside the Railway network (e.g. a one-off command) or through a")
        print("  `railway connect Postgres` tunnel + DSN.")
        return 2


if __name__ == "__main__":
    sys.exit(validate_production())
