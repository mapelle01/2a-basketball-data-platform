#!/usr/bin/env python3
"""Historical backfill runner — public FEB pages → ingest commands.

Ties the pieces together: the public calendar (`discover_matches`) lists a
season's matches; for each, the public match page (`parse_public_boxscore`) is
fetched and parsed into a full boxscore (incl. shooting/VAL/+-/quarters); it is
mapped to three commands (create_or_update_match → upsert_match_stats →
finalize_match) and POSTed to the ingest API. Tokenless source; idempotent
command ids make re-runs and overlap with LiveStats safe; rate-limited and
isolated per match so one bad page never aborts the season.

The core ``run_backfill`` is dependency-injected (fetch/post) so it is unit
tested offline; ``main`` wires the real calendar, fetch and HTTP POST.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import parse_public_boxscore as PPB

_OK_STATUSES = {200, 201, 202, 204}
_COMMANDS = ("create_or_update_match", "upsert_match_stats", "finalize_match")


@dataclass(frozen=True)
class MatchTask:
    external_id: str
    round_number: Optional[int] = None
    scheduled_at: Optional[str] = None
    source_url: Optional[str] = None


def _score_consistency_delta(box: "PPB.PublicBoxscore") -> Optional[str]:
    """None when the score is self-consistent (Σ quarters == final score per
    team); otherwise a short mismatch description. This gates genuine score
    parse/data errors — NOT incomplete per-player boxscores (see _player_gap):
    FEB sometimes publishes a valid final score whose player rows don't add up,
    and those matches are still worth ingesting."""
    for team in (box.home, box.away):
        if team.quarters and sum(team.quarters) != team.score:
            return (f"home q{sum(box.home.quarters)}/{box.home.score}, "
                    f"away q{sum(box.away.quarters)}/{box.away.score}")
    return None


def _player_gap(box: "PPB.PublicBoxscore") -> Optional[str]:
    """Informational: Σ player points != final score for a team (FEB's per-player
    data is incomplete). The match still ingests; the score/quarters are valid."""
    hs = sum(p.points for p in box.players_of(box.home.external_id))
    as_ = sum(p.points for p in box.players_of(box.away.external_id))
    if hs == box.home.score and as_ == box.away.score:
        return None
    return f"home Σ{hs}/{box.home.score}, away Σ{as_}/{box.away.score}"


def build_commands(box: "PPB.PublicBoxscore", task: MatchTask,
                   season_code: str, competition_id: str) -> List[tuple]:
    """The three (command_type, command) tuples for one match, in POST order."""
    return [
        ("create_or_update_match", PPB.to_match_command(
            box, season_code, competition_id, round_number=task.round_number,
            scheduled_at=task.scheduled_at, source_url=task.source_url)),
        ("upsert_match_stats", PPB.to_stats_command(
            box, season_code, competition_id, played_at=task.scheduled_at)),
        ("finalize_match", PPB.to_finalize_command(
            box, season_code, competition_id)),
    ]


def run_backfill(
    tasks: Iterable[MatchTask],
    *,
    season_code: str,
    competition_id: str,
    fetch: Callable[[str], str],
    post: Callable[[str, Dict[str, Any]], int],
    sleep_s: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    limit: Optional[int] = None,
    dry_run: bool = False,
    check_integrity: bool = True,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """Fetch→parse→map→POST each match. Isolated per match, rate-limited, idempotent.
    Returns a summary dict."""
    summary: Dict[str, Any] = {"seen": 0, "ok": 0, "failed": 0, "skipped": 0,
                               "errors": [], "skips": [], "warnings": []}
    for task in tasks:
        if limit is not None and summary["seen"] >= limit:
            break
        summary["seen"] += 1
        ext = str(task.external_id)
        try:
            box = PPB.parse_public_boxscore(fetch(ext), ext)
            delta = _score_consistency_delta(box) if check_integrity else None
            if delta is not None:
                summary["skipped"] += 1
                summary["skips"].append({"external_id": ext, "detail": delta})
                log(f"skip {ext}: score inconsistent ({delta})")
            elif dry_run:
                gap = _player_gap(box) if check_integrity else None
                if gap is not None:
                    summary["warnings"].append({"external_id": ext, "detail": gap})
                summary["ok"] += 1
                log(f"[dry-run] {ext}: {box.home.name} {box.home.score}-"
                    f"{box.away.score} {box.away.name} · {len(box.players)}p"
                    + (f" · WARN incomplete players ({gap})" if gap else ""))
            else:
                gap = _player_gap(box) if check_integrity else None
                if gap is not None:
                    summary["warnings"].append({"external_id": ext, "detail": gap})
                    log(f"warn {ext}: incomplete player boxscore ({gap})")
                failure = None
                for ctype, cmd in build_commands(box, task, season_code, competition_id):
                    status = post(ctype, cmd)
                    if status not in _OK_STATUSES:
                        failure = f"{ctype} HTTP {status}"
                        break
                if failure:
                    summary["failed"] += 1
                    summary["errors"].append({"external_id": ext, "error": failure})
                    log(f"FAIL {ext}: {failure}")
                else:
                    summary["ok"] += 1
                    log(f"ok {ext}")
        except Exception as exc:  # noqa: BLE001 — per-match isolation
            summary["failed"] += 1
            summary["errors"].append({"external_id": ext, "error": str(exc)[:200]})
            log(f"ERROR {ext}: {str(exc)[:120]}")
        if sleep_s and not dry_run:
            sleep_fn(sleep_s)
    return summary


# ---------------------------------------------------------------------------
# CLI wiring (real calendar + fetch + HTTP POST)
# ---------------------------------------------------------------------------


def _discover_tasks(season_code: str, competition: str, group: str,
                    conference: str = "ESTE") -> List[MatchTask]:
    """Matches of one CONFERENCE of the competition.

    Segunda FEB is split in two conferences (ESTE / OESTE) and the calendar GET
    returns only the first, so a backfill that ignores this silently ingests HALF
    a league — which then makes any "season leader" a leader of one conference
    only. The second is reached through the page's own ASP.NET group dropdown,
    which is read from the fetched page and therefore works for past seasons too
    (``discover_matches.fetch_calendar_group`` cannot be used here: it is gated
    to the single configured season).
    """
    import discover_matches as DM

    year = season_code.split("-")[0]
    url = f"https://baloncestoenvivo.feb.es/calendario.aspx?g={group}&t={year}&nm={competition}"
    page = DM.fetch_calendar(url)
    if conference.upper() != "ESTE":
        page = DM._post_grupo(url, page, conference.upper())
    by_round = DM.parse_calendar(page)
    tasks: List[MatchTask] = []
    for rnum in sorted(by_round):
        for ref in by_round[rnum]:
            tasks.append(MatchTask(str(ref.external_id), ref.round_number,
                                   ref.scheduled_at, ref.source_url))
    return tasks


def _clean_env(name: str) -> str:
    """Env value with whitespace and stray surrounding quotes stripped.

    Guards against pasting a key with smart/curly quotes (`“…”`), which would
    otherwise crash urllib's latin-1 header encoding.
    """
    v = os.environ.get(name, "").strip()
    return v.strip("'\"“”‘’`").strip()


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
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (own ingest API)
                return resp.status
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")[:500]
                print(f"    ↳ {command_type} {exc.code}: {body}", file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass
            return exc.code
    return post


def main() -> int:
    ap = argparse.ArgumentParser(description="FEB public historical backfill")
    ap.add_argument("--season", required=True, help="e.g. 2018-2019")
    ap.add_argument("--competition", default="segundafeb")
    ap.add_argument("--group", default="2")
    ap.add_argument("--conference", default="ESTE", choices=["ESTE","OESTE"],
                    help="Segunda FEB conference; the calendar GET only returns ESTE")
    ap.add_argument("--rounds", default=None, help="csv of round numbers to limit to")
    ap.add_argument("--limit", type=int, default=None, help="max matches")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between matches")
    ap.add_argument("--dry-run", action="store_true", help="fetch+parse only, no POST")
    args = ap.parse_args()

    tasks = _discover_tasks(args.season, args.competition, args.group, args.conference)
    if args.rounds:
        want = {int(x) for x in args.rounds.split(",")}
        tasks = [t for t in tasks if t.round_number in want]

    if args.dry_run:
        post: Callable[[str, Dict[str, Any]], int] = lambda ctype, cmd: 200  # noqa: E731
    else:
        base = _clean_env("FEB_TARGET_API")
        key = _clean_env("FEB_API_KEY")
        if not base or not key:
            raise SystemExit("CONFIG_ERROR: FEB_TARGET_API and FEB_API_KEY are required")
        post = _http_post(base, key)

    summary = run_backfill(
        tasks, season_code=args.season, competition_id=args.competition,
        fetch=lambda ext: PPB.fetch_match_page(str(ext)), post=post,
        sleep_s=args.sleep, limit=args.limit, dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
