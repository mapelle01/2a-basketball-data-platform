#!/usr/bin/env python3
"""Finalize matches that were ingested with their boxscore but never closed.

WHY THIS EXISTS
---------------
Half of 2025-2026 was ingested under a second competition id (``segunda-feb``
alongside ``segundafeb``) and left SCHEDULED. Those matches are NOT missing
data: they carry their full boxscore — team stats and 20+ player lines — but no
``score_summary``, so the aggregate never reached FINALIZED. The content engine
only looks at finalized matches, so every card for that season was being built
from half the league: a "quinteto de la jornada" that validates perfectly while
being the best five of half a round.

Nothing needs re-fetching from the FEB. The score is already in the stored team
stats (each team's ``points_for``), so this only replays the missing
``finalize_match`` command.

SAFETY
------
* Reads only; the sole write is one finalize_match per match.
* Command ids are the SAME deterministic UUIDv5 the ingest runner uses, so a
  re-run is idempotent and cannot double-apply.
* A match is skipped unless BOTH teams' stats are present and the two rows
  agree (home.points_for == away.points_against). A disagreeing pair is
  reported, never guessed at.
* --dry-run prints exactly what it would send and posts nothing.

USAGE
-----
    export FEB_TARGET_API=https://…      # your API base
    export FEB_API_KEY=…                 # your own API key (never logged)
    python scripts/feb/finalize_pending.py --season 2025-2026 --dry-run
    python scripts/feb/finalize_pending.py --season 2025-2026
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

_COMMAND_VERSION = "1.0"
_ACTOR = {"id": "feb-score-ingestor", "role": "system"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _finalize_command_id(season_code: str, competition_id: str, external_id: str) -> str:
    """The SAME id the ingest runner would have produced, so replaying this is
    idempotent with the original pipeline rather than a parallel write."""
    name = f"{season_code}|{competition_id}|{external_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score-ingestor-finalize:{name}"))


def _clean_env(name: str) -> str:
    """Env value with whitespace and stray surrounding quotes stripped — a key
    pasted with curly quotes would otherwise crash urllib's latin-1 headers."""
    return os.environ.get(name, "").strip().strip("'\"“”‘’`").strip()


@dataclasses.dataclass
class Stats:
    seen: int = 0
    already_final: int = 0
    finalized: int = 0
    skipped_no_stats: int = 0
    skipped_inconsistent: int = 0
    failed: int = 0


def score_from_team_stats(
    match: Dict[str, Any], detail: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """(home_score, away_score) from the stored team stats, or None when they
    are absent or disagree. Each team row carries points_for and
    points_against, so the pair is self-checking: the home team's points_for
    must equal the away team's points_against."""
    rows = {t["team_external_id"]: t for t in (detail.get("team_stats") or [])}
    home_id, away_id = match["home_team_id"], match["away_team_id"]
    home, away = rows.get(home_id), rows.get(away_id)
    if home is None or away is None:
        return None
    hs, as_ = home.get("points_for"), away.get("points_for")
    if hs is None or as_ is None:
        return None
    if home.get("points_against") != as_ or away.get("points_against") != hs:
        return None
    return int(hs), int(as_)


def build_finalize(match: Dict[str, Any], home_score: int, away_score: int) -> Dict[str, Any]:
    """The finalize command. No periods: the stored team stats do not carry
    quarters, and the contract makes them optional — a score-only finalization
    is honest, an invented quarter split would not be."""
    return {
        "command_id": _finalize_command_id(
            match["season_code"], match["competition_id"], match["external_id"]
        ),
        "meta": {"version": _COMMAND_VERSION, "issued_at": _now_iso()},
        "actor": dict(_ACTOR),
        "payload": {
            "match_external_id": match["external_id"],
            "score_summary": {"home_score": home_score, "away_score": away_score},
        },
    }


def _http_get(base_url: str) -> Callable[[str], Dict[str, Any]]:
    def get(path: str) -> Dict[str, Any]:
        with urllib.request.urlopen(  # noqa: S310 (our own API)
            f"{base_url.rstrip('/')}{path}", timeout=30
        ) as resp:
            return json.load(resp)
    return get


def _http_post(base_url: str, api_key: str) -> Callable[[str, Dict[str, Any]], int]:
    def post(command_type: str, command: Dict[str, Any]) -> int:
        body = json.dumps({"command_id": command["command_id"], "payload": command["payload"]})
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/commands/{command_type}",
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}",
                     "X-Request-Id": command["command_id"]},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return resp.status
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
                print(f"    ↳ {command_type} {exc.code}: {detail}", file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass
            return exc.code
    return post


def run(season: str, rounds: range, *, get, post, dry_run: bool,
        verbose: bool = False) -> Stats:
    stats = Stats()
    for rnd in rounds:
        try:
            matches = get(
                f"/v1/matches/search?season_code={season}&round_number={rnd}&limit=100"
            )["items"]
        except Exception as exc:  # noqa: BLE001 — one bad round must not stop the run
            print(f"J{rnd}: no se pudo leer ({type(exc).__name__})", file=sys.stderr)
            continue
        for m in matches:
            stats.seen += 1
            if m.get("status") == "FINALIZED":
                stats.already_final += 1
                continue
            try:
                detail = get(f"/v1/matches/{m['external_id']}")
            except Exception:  # noqa: BLE001
                stats.failed += 1
                continue
            score = score_from_team_stats(m, detail)
            if score is None:
                rows = detail.get("team_stats") or []
                if len(rows) < 2:
                    stats.skipped_no_stats += 1
                else:
                    stats.skipped_inconsistent += 1
                    print(f"  J{rnd} {m['external_id']}: marcador incoherente, se omite",
                          file=sys.stderr)
                continue
            cmd = build_finalize(m, *score)
            if dry_run:
                if verbose:
                    print(f"  J{rnd} {m['external_id']} [{m['competition_id']}] "
                          f"→ {score[0]}-{score[1]}")
                stats.finalized += 1
                continue
            code = post("finalize_match", cmd)
            if 200 <= code < 300:
                stats.finalized += 1
            else:
                stats.failed += 1
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", required=True, help="e.g. 2025-2026")
    ap.add_argument("--rounds", default="1-34", help="range, e.g. 1-34")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    lo, _, hi = args.rounds.partition("-")
    rounds = range(int(lo), int(hi or lo) + 1)

    base = _clean_env("FEB_TARGET_API")
    if not base:
        raise SystemExit("CONFIG_ERROR: FEB_TARGET_API is required")
    get = _http_get(base)
    post: Callable[[str, Dict[str, Any]], int]
    if args.dry_run:
        def post(_t, _c):  # pragma: no cover - never called in a dry run
            return 200
    else:
        key = _clean_env("FEB_API_KEY")
        if not key:
            raise SystemExit("CONFIG_ERROR: FEB_API_KEY is required (use --dry-run to preview)")
        post = _http_post(base, key)

    stats = run(args.season, rounds, get=get, post=post,
                dry_run=args.dry_run, verbose=args.verbose)
    print(json.dumps(dataclasses.asdict(stats), indent=1))
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
