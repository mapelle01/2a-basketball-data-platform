#!/usr/bin/env python3
"""FASE 25 — Auto-ingest orchestrator for a running season.

Drives the whole ingestion loop for the active season (``FEB_SEASON_CODE`` or
default ``2025-2026``) so the system keeps ingesting on its own:

  daily  (default): discover the season calendar, pick the "active rounds" (the
         last round whose date has passed plus the next upcoming round) and
         ingest them via ``ingest_round.run_round`` (fetch BoxScore -> POST
         create_or_update_match + upsert_match_stats, idempotent by UUIDv5).
  weekly (--weekly / FEB_INGEST_MODE=weekly): full-season sweep of every round.

After ingestion, the orchestrator triggers the server-side ``backfill_catalog``
command (POST /v1/commands/backfill_catalog) so player/team catalog names are
refreshed from the official FEB source without exposing DB credentials to the
runner (the API owns the DB writes).

Environment:
    FEB_SEASON_CODE   season to process (default 2025-2026)
    FEB_TARGET_API    API base URL (required for POST; e.g. https://...)
    FEB_API_KEY       raw 64-hex API key (required for POST)
    FEB_INGEST_MODE   daily | weekly (default daily; --weekly overrides)
    FEB_GROUPS        comma-separated groups (default ESTE,OESTE)

Security: never prints FEB_TOKEN / API key / Authorization headers. Errors are
sanitized by the reused ingest_round machinery.

Exit codes:
    0  success
    1  at least one round failed
    2  configuration error
    3  discovery/source error
    6  unexpected error
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import discover_matches as DM  # noqa: E402  (FASE 22.1)
import ingest_round as IR      # noqa: E402  (FASE 22.2)

DEFAULT_SEASON = "2025-2026"
DEFAULT_GROUPS = ("ESTE", "OESTE")
DAILY_LOOKBACK_DAYS = 10   # include the last round whose date has passed
DAILY_LOOKAHEAD_DAYS = 14  # plus upcoming rounds within two weeks


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    return v or default


def _season() -> str:
    return _env("FEB_SEASON_CODE", DM._configured_season()) or DEFAULT_SEASON


def _groups() -> List[str]:
    raw = _env("FEB_GROUPS", ",".join(DEFAULT_GROUPS))
    groups = [g.strip().upper() for g in raw.split(",") if g.strip()]
    if not groups:
        raise ConfigError("FEB_GROUPS must contain at least one group")
    for g in groups:
        if g not in DM.SUPPORTED_GROUPS:
            raise ConfigError(
                f"unsupported group {g!r}; supported: {', '.join(DM.SUPPORTED_GROUPS)}"
            )
    return groups


def _active_rounds(by_round: Dict[int, List[DM.MatchRef]], today: date) -> List[int]:
    """Rounds whose scheduled date is within the lookback/lookahead window.

    ``scheduled_at`` is ISO with an offset; we compare the calendar date.
    Rounds are sorted ascending; returns at least the last already-played round
    and the next upcoming one when the season has started.
    """
    windows: Dict[int, List[date]] = {}
    for round_number, refs in by_round.items():
        for ref in refs:
            iso = ref.scheduled_at[:10]
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                continue
            windows.setdefault(round_number, []).append(d)

    active: List[int] = []
    for round_number, dates in windows.items():
        if any(today - timedelta(days=DAILY_LOOKBACK_DAYS) <= d <= today + timedelta(days=DAILY_LOOKAHEAD_DAYS) for d in dates):
            active.append(round_number)
    return sorted(active)


def _post_backfill(season_code: str, target: str, api_key: str) -> Dict[str, object]:
    """Trigger the server-side ``backfill_catalog`` command (admin role)."""
    import json  # noqa: PLC0415 (local; only used for POST body)
    import uuid  # noqa: PLC0415

    body = json.dumps({
        "command_id": str(uuid.uuid4()),
        "meta": {"version": "1.0", "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "actor": {"id": "auto-ingest", "role": "admin"},
        "payload": {"season_code": season_code, "entity": "both", "dry_run": False},
    }).encode("utf-8")
    url = f"{target.rstrip('/')}/v1/commands/backfill_catalog"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 (configurable target)
            return {"status": resp.status, "body": resp.read().decode("utf-8", "replace")[:500]}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": exc.read().decode("utf-8", "replace")[:500]}


def run(mode: str, *, dry_run: bool = False) -> int:
    season = _season()
    groups = _groups()
    if season != DM._configured_season():
        print(f"CONFIG_ERROR: season {season!r} != configured {DM._configured_season()!r}", file=sys.stderr)
        return 2

    today = date.today()
    overall_failed = 0
    total_discovered = 0

    for group in groups:
        print(f"=== group={group} season={season} ===")
        try:
            html = DM.fetch_calendar_group(season, group)
        except DM.SourceError as exc:
            print(f"SOURCE_ERROR: {group}: {exc}", file=sys.stderr)
            overall_failed += 1
            continue
        by_round = DM.parse_calendar(html)
        if not by_round:
            print(f"group={group}: no rounds parsed", file=sys.stderr)
            overall_failed += 1
            continue

        if mode == "weekly":
            rounds = sorted(by_round)
        else:
            rounds = _active_rounds(by_round, today)
            print(f"active_rounds={rounds}")

        if dry_run:
            for r in rounds:
                print(f"round={r} discovered={len(by_round[r])}")
            total_discovered += sum(len(by_round[r]) for r in rounds)
            continue

        for round_number in rounds:
            total_discovered += len(by_round[round_number])
            rc = IR.run_round(season, round_number, group=group)
            if rc != 0:
                overall_failed += 1

    if dry_run:
        print(f"DRY_RUN matches={total_discovered}")
        return 0
    print(f"matches_discovered={total_discovered} failed_rounds={overall_failed}")

    # Trigger the server-side catalog backfill (only when NOT a dry run and the
    # API target + key are configured; the API owns DB writes).
    target = _env("FEB_TARGET_API")
    api_key = _env("FEB_API_KEY")
    if target and api_key:
        print("trigger backfill_catalog ...")
        res = _post_backfill(season, target, api_key)
        print(f"backfill_catalog HTTP {res['status']}")
        if res["status"] not in (200, 201, 204, 409):
            print(f"  body: {res['body']}", file=sys.stderr)
            overall_failed += 1
    else:
        print("skip backfill_catalog (FEB_TARGET_API/FEB_API_KEY not set)")

    return 0 if overall_failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="feb-auto-ingest")
    ap.add_argument("--season", default=None, help="season code (default env FEB_SEASON_CODE or 2025-2026)")
    ap.add_argument("--weekly", action="store_true", help="full-season sweep (default daily active rounds)")
    ap.add_argument("--dry-run", action="store_true", help="discover + report only; NO POST")
    args = ap.parse_args()

    if args.season:
        os.environ["FEB_SEASON_CODE"] = args.season

    mode = "weekly" if args.weekly else (_env("FEB_INGEST_MODE", "daily") or "daily")
    if mode not in ("daily", "weekly"):
        print(f"CONFIG_ERROR: FEB_INGEST_MODE must be daily|weekly, got {mode!r}", file=sys.stderr)
        return 2

    try:
        return run(mode, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except DM.SourceError as exc:
        print(f"SOURCE_ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"UNEXPECTED_ERROR: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    sys.exit(main())
