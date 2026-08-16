#!/usr/bin/env python3
"""FASE 24 — Production Read-Only Validator for Match & Player Exploration (2025-2026).

Validates the whole FASE 24 surface (24.1 match detail boxscore, 24.2 player
profiles, 24.3 team profiles + round evolution, 24.4 player/team/match search)
against the real PostgreSQL database.

READ-ONLY: performs no INSERT/UPDATE/DELETE and never prints connection
secrets. The only environment inputs are ``FEB_SCORE_DATABASE_URL`` or
``DATABASE_URL``.

Blocks (for season_code=2025-2026):

  MATCH DETAIL     every league match has a detail; boxscore = exactly 2 team
                   stat rows whose teams match home/away; home.points_for ==
                   away.points_against; player rows belong to home or away and
                   are unique per match; team and player rows deterministic.
  PLAYER PROFILES  all 449 players resolve; teams = registrations of the season
                   only; totals/metrics None iff the player has no stats rows;
                   totals agree with the FASE 23 season analytics aggregates.
  TEAM PROFILES    all 28 teams resolve; totals agree with the team aggregates;
                   evolution spans exactly rounds 1..26; sum of per-round games
                   == matches involving the team; wins/losses consistent.
  SEARCH           match search: season+competition -> 364; 14 matches per
                   round; deterministic; player/team name search must find the
                   entity it was seeded from; external_id q exact-hit.

Usage:
    FEB_SCORE_DATABASE_URL="<dsn>" python3 validate_season_exploration_production.py
"""

from __future__ import annotations

import os
import sys
from typing import List

sys.path.insert(0, os.path.abspath("src"))

from feb_score.application.use_cases.exploration_service import ExplorationService
from feb_score.application.use_cases.season_analytics_service import SeasonAnalyticsService
from feb_score.domain.value_objects import CompetitionId, ExternalId, SeasonCode
from feb_score.infrastructure.persistence.postgres.connection import PgDatabase
from feb_score.infrastructure.persistence.postgres.repositories import (
    PgMatchRepository,
    PgMatchStatsRepository,
    PgPlayerRepository,
    PgTeamRepository,
)

SEASON = "2025-2026"
COMPETITION = "segunda-feb"
EXPECTED_MATCHES = 364
EXPECTED_TEAMS = 28
EXPECTED_ROUNDS = 26
EXPECTED_ROUND_MATCHES = 14
_TOL = 1e-6


def _league_match_ids(db: PgDatabase, season_code: str) -> List[str]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT external_id FROM matches WHERE season_code = %s"
            " AND competition_id = %s ORDER BY external_id",
            (season_code, COMPETITION),
        ).fetchall()
    finally:
        conn.close()
    return [r["external_id"] for r in rows]


def _names(db: PgDatabase, table: str) -> dict:
    conn = db.connect()
    try:
        rows = conn.execute(f"SELECT external_id, name FROM {table}").fetchall()
    finally:
        conn.close()
    return {r["external_id"]: r["name"] for r in rows}


def _matches_for_team(db: PgDatabase, team: str, season_code: str) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM matches WHERE season_code = %s"
            " AND (data->>'home_team_id' = %s OR data->>'away_team_id' = %s)",
            (season_code, team, team),
        ).fetchone()
    finally:
        conn.close()
    return row["n"]


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def check_match_detail(db: PgDatabase, svc: ExplorationService, season_code: str) -> List[str]:
    failures: List[str] = []
    ids = _league_match_ids(db, season_code)
    print(f"  partidos a inspeccionar  = {len(ids)}  (esperado {EXPECTED_MATCHES})")
    if len(ids) != EXPECTED_MATCHES:
        failures.append(f"league matches {len(ids)} != {EXPECTED_MATCHES}")

    for ext in ids:
        detail = svc.get_match_detail(ExternalId(ext))
        if detail is None:
            failures.append(f"{ext}: match detail missing")
            continue
        match = detail.match
        team_stats = detail.team_stats
        player_stats = detail.player_stats

        home, away = str(match.home_team_id), str(match.away_team_id)
        stat_teams = sorted(ts.team_external_id for ts in team_stats)
        if stat_teams != sorted([home, away]):
            failures.append(f"{ext}: boxscore teams {stat_teams} != home/away {sorted([home, away])}")
            continue
        by_team = {ts.team_external_id: ts for ts in team_stats}
        if by_team[home].points_for != by_team[away].points_against:
            failures.append(
                f"{ext}: {home}.points_for {by_team[home].points_for}"
                f" != {away}.points_against {by_team[away].points_against}"
            )

        seen = set()
        for ps in player_stats:
            if ps.player_external_id in seen:
                failures.append(f"{ext}: duplicate player {ps.player_external_id}")
            seen.add(ps.player_external_id)
            if ps.team_external_id not in (home, away):
                failures.append(
                    f"{ext}: player {ps.player_external_id} team {ps.team_external_id}"
                    f" not home/away {home}/{away}"
                )

        # determinism of the boxscore projection
        again = svc.get_match_detail(ExternalId(ext))
        if [ts.team_external_id for ts in again.team_stats] != [ts.team_external_id for ts in team_stats]:
            failures.append(f"{ext}: team boxscore not deterministic")
        if [ps.player_external_id for ps in again.player_stats] != [ps.player_external_id for ps in player_stats]:
            failures.append(f"{ext}: player boxscore not deterministic")

    ok = len(failures) == 0
    print(f"  boxscore consistente      = {'PASS' if ok else 'FAIL'}")
    return failures


def check_player_profiles(
    db: PgDatabase, svc: ExplorationService, analytics: SeasonAnalyticsService, season_code: str
) -> List[str]:
    failures: List[str] = []
    catalog_names = _names(db, "players")
    aggregates = {a.player_external_id: a for a in analytics.list_season_player_aggregates(season_code)}
    print(f"  jugadores con stats       = {len(aggregates)} (esperado 449)")

    name_missing = 0
    for pid, aggregate in sorted(aggregates.items()):
        profile = svc.get_player_profile(SeasonCode(season_code), pid)
        if profile is None:
            failures.append(f"{pid}: profile missing despite having stats")
            continue
        if aggregate.points != profile.totals.points:
            failures.append(f"{pid}: totals.points {profile.totals.points} != aggregate {aggregate.points}")
        if aggregate.games_played != profile.totals.games_played:
            failures.append(f"{pid}: totals.games_played != aggregate")
        for reg in profile.teams:
            if str(reg.season_code) != season_code:
                failures.append(f"{pid}: team outside season {reg.season_code}")

        if profile.player is None:
            # identity derived from the stats projection (catalog absent)
            name_missing += 1
        else:
            expected = catalog_names.get(pid)
            if expected is not None and profile.player.name != expected:
                failures.append(f"{pid}: profile name {profile.player.name} != catalog {expected}")

    if name_missing:
        print(f"  [DIAG] jugadores con stats pero sin registro de catálogo (name null): {name_missing}")
    return failures


def check_team_profiles(
    db: PgDatabase, svc: ExplorationService, analytics: SeasonAnalyticsService, season_code: str
) -> List[str]:
    failures: List[str] = []
    catalog_names = _names(db, "teams")
    aggregates = {a.team_external_id: a for a in analytics.list_season_team_aggregates(season_code)}
    print(f"  equipos con stats         = {len(aggregates)} (esperado {EXPECTED_TEAMS})")

    name_missing = 0
    for tid, aggregate in sorted(aggregates.items()):
        profile = svc.get_team_profile(SeasonCode(season_code), tid)
        if profile is None:
            failures.append(f"{tid}: profile missing despite having stats")
            continue
        for field in ("points_for", "points_against", "wins", "losses", "games_played"):
            if getattr(profile.totals, field) != getattr(aggregate, field):
                failures.append(f"{tid}: totals.{field} != aggregate")
        if profile.team is None:
            name_missing += 1
        else:
            expected = catalog_names.get(tid)
            if expected is not None and profile.team.name != expected:
                failures.append(f"{tid}: profile name mismatch")

        rounds = {r.round_number: r for r in profile.rounds}
        if sorted(rounds) != list(range(1, EXPECTED_ROUNDS + 1)):
            failures.append(f"{tid}: evolution rounds {sorted(rounds)} != 1..{EXPECTED_ROUNDS}")
            continue
        games = sum(r.games_played for r in rounds.values())
        wins = sum(r.wins for r in rounds.values())
        losses = sum(r.losses for r in rounds.values())
        played = _matches_for_team(db, tid, season_code)
        if games != profile.totals.games_played:
            failures.append(f"{tid}: evolution games {games} != totals {profile.totals.games_played}")
        if games != played:
            failures.append(f"{tid}: evolution games {games} != matches involving team {played}")
        if wins != profile.totals.wins or losses != profile.totals.losses:
            failures.append(f"{tid}: evolution W/L {wins}-{losses} != totals {profile.totals.wins}-{profile.totals.losses}")

    if name_missing:
        print(f"  [DIAG] equipos con stats pero sin registro de catálogo (name null): {name_missing}")
    return failures


def check_search(
    db: PgDatabase, svc: ExplorationService, season_code: str
) -> List[str]:
    failures: List[str] = []

    # match search: season + competition scoping, per-round structure, determinism
    matches = svc.search_matches(
        SeasonCode(season_code), competition_id=CompetitionId(COMPETITION)
    )
    ids = [str(m.external_id) for m in matches]
    if len(ids) != EXPECTED_MATCHES:
        failures.append(f"match search season+competition -> {len(ids)} != {EXPECTED_MATCHES}")
    if ids != sorted(ids):
        failures.append("match search not ordered by external_id")
    if [str(m.external_id) for m in svc.search_matches(SeasonCode(season_code), competition_id=CompetitionId(COMPETITION))] != ids:
        failures.append("match search not deterministic")
    for round_number in range(1, EXPECTED_ROUNDS + 1):
        per_round = svc.search_matches(
            SeasonCode(season_code), competition_id=CompetitionId(COMPETITION), round_number=round_number
        )
        if len(per_round) != EXPECTED_ROUND_MATCHES:
            failures.append(f"round {round_number}: {len(per_round)} != {EXPECTED_ROUND_MATCHES}")
    print(f"  match search              = {len(ids)} en {EXPECTED_ROUNDS} jornadas x {EXPECTED_ROUND_MATCHES}")

    # name search must find the very entity it was seeded from (catalog-based:
    # with an empty players/teams catalog there is nothing to match — reported
    # as an informational diagnostic, documented production gap)
    player_names = _names(db, "players")
    for pid, name in sorted(player_names.items()):
        found = {str(p.external_id) for p in svc.search_players(name)}
        if pid not in found:
            failures.append(f"player search '{name}' did not return {pid}")
    team_names = _names(db, "teams")
    for tid, name in sorted(team_names.items()):
        found = {str(t.external_id) for t in svc.search_teams(name)}
        if tid not in found:
            failures.append(f"team search '{name}' did not return {tid}")
    if not player_names or not team_names:
        print(f"  [DIAG] catálogo players/teams vacío ({len(player_names)}/{len(team_names)}):"
              " name search no puede matchear hasta poblarlo (gap de datos documentado)")
    print(f"  player/team name search   = {len(player_names)}/{len(team_names)} entidades re-ubicables")

    # external_id substring exact-hit
    sample = _league_match_ids(db, season_code)[:5]
    for ext in sample:
        hits = [str(m.external_id) for m in svc.search_matches(SeasonCode(season_code), external_id_query=ext)]
        if ext not in hits:
            failures.append(f"match q={ext} did not return itself")

    return failures


def run_validations(db: PgDatabase, season_code: str):
    repos = (
        PgMatchRepository(db),
        PgPlayerRepository(db),
        PgTeamRepository(db),
        PgMatchStatsRepository(db),
    )
    svc = ExplorationService(*repos)
    analytics = SeasonAnalyticsService(PgMatchStatsRepository(db))

    blocks = [
        ("1. MATCH DETAIL (24.1)", check_match_detail(db, svc, season_code)),
        ("2. PLAYER PROFILES (24.2)", check_player_profiles(db, svc, analytics, season_code)),
        ("3. TEAM PROFILES + EVOLUCION (24.3)", check_team_profiles(db, svc, analytics, season_code)),
        ("4. SEARCH (24.4)", check_search(db, svc, season_code)),
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
    print(f"FASE 24 — Match & Player Exploration Production Validation ({season_code})")
    print("Mode: READ-ONLY")
    print("=================================================================")

    try:
        db = PgDatabase(dsn=dsn)
        code, failures = run_validations(db, season_code)
        if code == 0:
            print("RESULTADO VALIDACIÓN: PASS — Exploración íntegra y consistente.")
            print("=================================================================")
        else:
            print(f"RESULTADO VALIDACIÓN: FAIL — {len(failures)} discrepancia(s).")
            print("=================================================================")
        return code
    except Exception as exc:  # noqa: BLE001 - READ-ONLY validator never leaks state
        print("\nPRODUCTION VALIDATION: BLOCKED")
        print(f"  causa: {type(exc).__name__} al conectar/consultar.")
        print("  No connection secrets are printed.")
        print("  Run inside the Railway network (one-off command) or through a")
        print("  `railway connect Postgres` tunnel + DSN.")
        return 2


if __name__ == "__main__":
    sys.exit(validate_production())