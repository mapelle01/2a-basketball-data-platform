#!/usr/bin/env python3
"""FASE 24.1 — Production Catalog Backfill (players/teams).

Pobla los catálogos ``players``/``teams`` de la temporada pedida desde el
conjunto canónico de entidades (external_ids con stats en ``match_player_stats``
/ ``match_team_stats``) + un resolutor oficial de nombres.

Regla de identidad (canónica, inalterada):
  * Player identity = ``player_external_id``
  * Team identity   = ``team_external_id``
Los nombres son atributos descriptivos; nunca son identidad, nunca se usan para
fusionar entidades.

Fuente de verdad oficial de nombres:
  * Equipos -> calendario público FEB (baloncestoenvivo.feb.es, ESTE+OESTE;
    misma fuente que el discovery FASE 22.1/22.5, sin token). Se cruza el id de
    partido del calendario con ``matches`` para mapear (home/away) -> id de
    equipo, y se aplica la política determinista: nombre más frecuente;
    empate -> lexicográficamente menor.
  * Jugadores -> no hay fuente oficial disponible sin ``FEB_TOKEN`` (los
    BoxScore intrafeb llevan los nombres pero la token no está disponible):
    se crean con ``name = NULL`` (gap documentado).

Política de escritura (determinista, documentada):
  * external_id nuevo            -> crear (name NULL si no hay nombre oficial)
  * existente con name NULL/''   -> rellenar si hay nombre oficial
  * existente con name válido =  -> skip
  * existente con name válido != -> conservar existente + warning

Idempotente y reejecutable: una segunda ejecución sin cambios reporta
``created=0 updated=0 skipped=N errors=0``. Solo escribe en los catálogos;
nunca modifica stats, matches ni eventos.

Seguridad:
  * DSN vía env ``FEB_SCORE_DATABASE_URL``/``DATABASE_URL`` o ``--database-url``;
    nunca se imprime.
  * Sin secrets en Git. Las URLs FEB son públicas (calendario) y no llevan token.
  * ``--dry-run``: calcula y reporta SIN escribir.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)  # sibling scripts (discover_matches) under any loader
sys.path.insert(0, os.path.dirname(ROOT))  # repo root -> src importable

from feb_score.application.use_cases.catalog_backfill_service import (  # noqa: E402
    CatalogBackfillService,
)
from feb_score.application.use_cases.player_name_resolver import (  # noqa: E402
    OfficialPlayerNameResolver,
    SourceError,
)
from feb_score.domain.value_objects import SeasonCode  # noqa: E402

DEFAULT_SEASON = "2025-2026"
SUPPORTED_GROUPS = ("ESTE", "OESTE")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    return v or default


def _require_env(name: str) -> str:
    v = _env(name)
    if v is None:
        raise SystemExit(f"CONFIG_ERROR: missing required env var: {name}")
    return v


# ---------------------------------------------------------------------------
# Team name resolution from the official public FEB calendar
# ---------------------------------------------------------------------------


def resolve_team_names_from_calendar(
    season_code: str,
    matches: List[tuple],
    calendar_html_by_group: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Official team names keyed by team_external_id.

    ``matches``: list of (match_external_id: str, home_team_id: str, away_team_id: str).
    ``calendar_html_by_group`` maps ESTE/OESTE -> calendar HTML (offline/tests);
    when None the live public calendar is fetched.

    Deterministic policy per team: most frequent name wins; ties are broken by
    the lexicographically smallest name (stable across runs).
    """
    import discover_matches as DM  # sibling script (FASE 22.1/22.5)

    by_match = {str(ext): (home, away) for ext, home, away in matches}
    candidates: Dict[str, List[str]] = defaultdict(list)

    for group in SUPPORTED_GROUPS:
        if calendar_html_by_group is not None:
            html = calendar_html_by_group.get(group)
            if not html:
                continue
        else:
            html = DM.fetch_calendar_group(season_code, group)
        by_round = DM.parse_calendar(html)
        for round_number, refs in by_round.items():
            for ref in refs:
                pair = by_match.get(str(ref.external_id))
                if pair is None:
                    continue
                home_id, away_id = pair
                candidates[home_id].append(ref.home_team.strip())
                candidates[away_id].append(ref.away_team.strip())

    resolved: Dict[str, str] = {}
    for team_id, names in candidates.items():
        if not names:
            continue
        counts = Counter(names)
        top = max(counts.values())
        winners = sorted(n for n, c in counts.items() if c == top)
        resolved[team_id] = winners[0]
    return resolved


# ---------------------------------------------------------------------------
# Catalog backfill runner
# ---------------------------------------------------------------------------


def _open_database(dsn: str):
    if dsn.startswith("sqlite:") or dsn.endswith(".sqlite3") or dsn.endswith(".db"):
        from feb_score.infrastructure.persistence.connection import SqliteDatabase

        path = dsn[7:] if dsn.startswith("sqlite:") else dsn
        db = SqliteDatabase(path)
        db.migrate()
        return db
    from feb_score.infrastructure.persistence.postgres.connection import PgDatabase

    db = PgDatabase(dsn)
    db.migrate()
    return db


def _build_repos(db):
    from feb_score.infrastructure.persistence import repositories as sqlite_r
    from feb_score.infrastructure.persistence.postgres import repositories as pg_r

    if db.__class__.__name__ == "SqliteDatabase":
        return (
            sqlite_r.SqliteMatchRepository(db),
            sqlite_r.SqliteMatchStatsRepository(db),
            sqlite_r.SqlitePlayerRepository(db),
            sqlite_r.SqliteTeamRepository(db),
        )
    return (
        pg_r.PgMatchRepository(db),
        pg_r.PgMatchStatsRepository(db),
        pg_r.PgPlayerRepository(db),
        pg_r.PgTeamRepository(db),
    )


class _MapResolver:
    def __init__(self, mapping: Dict[str, str]) -> None:
        self._mapping = mapping

    def resolve(self, season_code):
        return dict(self._mapping)


class _CalendarTeamResolver:
    def __init__(self, match_repo, season_code: str, html: Optional[Dict[str, str]] = None) -> None:
        self._match_repo = match_repo
        self._season = season_code
        self._html = html
        self._cached: Optional[Dict[str, str]] = None

    def resolve(self, season_code):
        if self._cached is None:
            matches = [
                (str(m.external_id), str(m.home_team_id), str(m.away_team_id))
                for m in self._match_repo.search(SeasonCode(self._season))
            ]
            self._cached = resolve_team_names_from_calendar(
                self._season, matches, self._html
            )
        return dict(self._cached)


class _PlayerNullResolver:
    def resolve(self, season_code):
        return {}


def _player_name_resolver(args, match_repo, stats_repo, season_code):
    """Return (resolver_or_none, OfficialPlayerNameResolver_or_None).

    With --player-names official the resolver is fail-closed on missing FEB_TOKEN
    (controlled SourceError; never invents names). With `none` returns the
    legacy NULL resolver (FASE 24.1 behavior).
    """
    if args.player_names == "none":
        return _PlayerNullResolver(), None
    token = args.feb_token or _env("FEB_TOKEN")
    if not token:
        raise SystemExit(
            "CONFIG_ERROR: --player-names official requires FEB_TOKEN "
            "(env FEB_TOKEN or --feb-token); never hardcoded/logged. "
            "Falling back without names is intentional — pass --player-names none."
        )
    resolver = OfficialPlayerNameResolver(
        match_repo, stats_repo, season_code, token=token,
    )
    return resolver, resolver


def _print_stats(prefix: str, stats) -> None:
    print(f"{prefix} created={stats.created} updated={stats.updated} "
          f"skipped={stats.skipped} errors={stats.errors}")
    for w in stats.warnings:
        print(f"{prefix} WARNING {w}")


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-backfill-catalog")
    ap.add_argument("--season", default=_env("FEB_SEASON_CODE", DEFAULT_SEASON), help="season code (default 2025-2026)")
    ap.add_argument("--entity", choices=["players", "teams", "both"], default="both")
    ap.add_argument("--database-url", default=None, help="PostgreSQL DSN or sqlite path (default env FEB_SCORE_DATABASE_URL/DATABASE_URL)")
    ap.add_argument("--dry-run", action="store_true", help="report only; never write")
    ap.add_argument("--calendar", action="append", default=[], metavar="GROUP=PATH",
                    help="offline calendar HTML per group (e.g. --calendar ESTE=fixture.html); may repeat")
    ap.add_argument("--player-names", choices=["none", "official"], default="none",
                    help="player name source (none=NULL; official=FEB BoxScore via FEB_TOKEN)")
    ap.add_argument("--feb-token", default=None,
                    help="FEB BoxScore API token (intrafeb); prefer env FEB_TOKEN; never logged/printed")
    args = ap.parse_args()

    season = SeasonCode(args.season)
    dsn = args.database_url or _require_env("FEB_SCORE_DATABASE_URL") or _require_env("DATABASE_URL")

    calendar_html: Dict[str, str] = {}
    for item in args.calendar:
        group, _, path = item.partition("=")
        if group.upper() not in SUPPORTED_GROUPS:
            print(f"CONFIG_ERROR: unknown calendar group {group!r}", file=sys.stderr)
            return 2
        with open(path, "rb") as f:
            calendar_html[group.upper()] = f.read().decode("utf-8")

    db = _open_database(dsn)
    match_repo, stats_repo, player_repo, team_repo = _build_repos(db)

    if args.entity in ("players", "both"):
        print("backfill players ...")
        player_names, player_resolver = _player_name_resolver(
            args, match_repo, stats_repo, str(season)
        )
        svc = CatalogBackfillService(
            player_repo, team_repo, stats_repo,
            player_names=player_names,
        )
        stats = svc.run(season, entities=("players",), dry_run=args.dry_run)
        _print_stats("players", stats)
        if player_resolver is not None:
            r, u, c = player_resolver.last_stats()
            print(f"players official-name report: resolved={r} unresolved={u} conflicts={c}")

    if args.entity in ("teams", "both"):
        print("backfill teams (official names via public FEB calendar) ...")
        try:
            team_names = _CalendarTeamResolver(match_repo, str(season), calendar_html or None)
            svc = CatalogBackfillService(
                player_repo, team_repo, stats_repo,
                team_names=team_names,
            )
            stats = svc.run(season, entities=("teams",), dry_run=args.dry_run)
            _print_stats("teams", stats)
        except Exception as exc:  # noqa: BLE001 - calendar is optional (fallback NULL)
            print(f"teams WARNING calendar resolution failed ({exc}); names left NULL")
            svc = CatalogBackfillService(player_repo, team_repo, stats_repo)
            stats = svc.run(season, entities=("teams",), dry_run=args.dry_run)
            _print_stats("teams (no names)", stats)

    return 0


if __name__ == "__main__":
    sys.exit(run())