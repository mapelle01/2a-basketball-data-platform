"""Backfill runner orchestration (offline, dependency-injected).

Proves the runner fetches→parses→maps→POSTs the three commands in order per
match, isolates a bad match without aborting the season, honours dry-run/limit,
skips integrity failures, and that the create+finalize commands it emits are
schema-valid across eras.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

from feb_score.application.validation import validate_command

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/ingestion/fixtures"
FEB_SCRIPTS = ROOT / "scripts" / "feb"

# The runner does `import parse_public_boxscore` — put its dir on the path first.
if str(FEB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(FEB_SCRIPTS))

_spec = importlib.util.spec_from_file_location("backfill_public", FEB_SCRIPTS / "backfill_public.py")
BF = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = BF
_spec.loader.exec_module(BF)

SEASON = "2025-2026"
COMP = "segundafeb"


def _html(match_id: str) -> str:
    return (FIX / f"partido_{match_id}.html").read_text(encoding="utf-8")


def _fake_fetch(mapping):
    def fetch(ext):
        if ext not in mapping:
            raise RuntimeError(f"no fixture for {ext}")
        return mapping[ext]
    return fetch


class _Recorder:
    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def __call__(self, command_type, command):
        self.calls.append((command_type, command))
        return self.status


def _tasks(*ids):
    return [BF.MatchTask(i, round_number=n + 1, scheduled_at="2025-10-04T18:00:00+02:00")
            for n, i in enumerate(ids)]


def test_posts_three_commands_in_order_per_match():
    fetch = _fake_fetch({"2486849": _html("2486849"), "29232": _html("29232")})
    post = _Recorder()
    summary = BF.run_backfill(_tasks("2486849", "29232"), season_code=SEASON,
                              competition_id=COMP, fetch=fetch, post=post,
                              sleep_s=0, log=lambda *_: None)
    assert summary["ok"] == 2 and summary["failed"] == 0 and summary["skipped"] == 0
    assert [c[0] for c in post.calls] == [
        "create_or_update_match", "upsert_match_stats", "finalize_match",
        "create_or_update_match", "upsert_match_stats", "finalize_match",
    ]


def test_create_and_finalize_commands_are_schema_valid():
    fetch = _fake_fetch({"2486849": _html("2486849")})
    post = _Recorder()
    BF.run_backfill(_tasks("2486849"), season_code=SEASON, competition_id=COMP,
                    fetch=fetch, post=post, sleep_s=0, log=lambda *_: None)
    by_type = {t: cmd for t, cmd in post.calls}
    validate_command(by_type["create_or_update_match"], "commands/create_or_update_match.v1.json")
    validate_command(by_type["upsert_match_stats"], "commands/upsert_match_stats.v1.json")
    validate_command(by_type["finalize_match"], "commands/finalize_match.v1.json")


def test_finalize_command_carries_score_and_periods():
    fetch = _fake_fetch({"2486849": _html("2486849")})
    post = _Recorder()
    BF.run_backfill(_tasks("2486849"), season_code=SEASON, competition_id=COMP,
                    fetch=fetch, post=post, sleep_s=0, log=lambda *_: None)
    fin = next(cmd for t, cmd in post.calls if t == "finalize_match")
    ss = fin["payload"]["score_summary"]
    assert (ss["home_score"], ss["away_score"]) == (78, 66)
    if "periods" in ss:  # included only when quarters reconcile with the score
        assert sum(p["home"] for p in ss["periods"]) == 78
        assert sum(p["away"] for p in ss["periods"]) == 66


def test_old_season_create_and_finalize_also_valid():
    fetch = _fake_fetch({"29232": _html("29232")})
    post = _Recorder()
    BF.run_backfill(_tasks("29232"), season_code="2005-2006", competition_id=COMP,
                    fetch=fetch, post=post, sleep_s=0, log=lambda *_: None)
    by_type = {t: cmd for t, cmd in post.calls}
    validate_command(by_type["create_or_update_match"], "commands/create_or_update_match.v1.json")
    validate_command(by_type["finalize_match"], "commands/finalize_match.v1.json")


def test_bad_match_is_isolated():
    fetch = _fake_fetch({"2486849": _html("2486849")})  # 999 missing → fetch raises
    post = _Recorder()
    summary = BF.run_backfill(_tasks("999", "2486849"), season_code=SEASON,
                              competition_id=COMP, fetch=fetch, post=post,
                              sleep_s=0, log=lambda *_: None)
    assert summary["seen"] == 2 and summary["ok"] == 1 and summary["failed"] == 1
    assert summary["errors"][0]["external_id"] == "999"
    # the good match still posted its full trio
    assert sum(1 for c in post.calls if c[0] == "finalize_match") == 1


def test_http_error_status_stops_that_match_only():
    fetch = _fake_fetch({"2486849": _html("2486849"), "29232": _html("29232")})
    post = _Recorder(status=500)
    summary = BF.run_backfill(_tasks("2486849", "29232"), season_code=SEASON,
                              competition_id=COMP, fetch=fetch, post=post,
                              sleep_s=0, log=lambda *_: None)
    assert summary["failed"] == 2 and summary["ok"] == 0
    # first command per match fails → no stats/finalize attempted
    assert [c[0] for c in post.calls] == ["create_or_update_match", "create_or_update_match"]
    assert "HTTP 500" in summary["errors"][0]["error"]


def test_dry_run_never_posts():
    fetch = _fake_fetch({"2486849": _html("2486849")})
    post = _Recorder()
    slept = []
    summary = BF.run_backfill(_tasks("2486849"), season_code=SEASON, competition_id=COMP,
                              fetch=fetch, post=post, dry_run=True, sleep_s=5,
                              sleep_fn=slept.append, log=lambda *_: None)
    assert summary["ok"] == 1 and post.calls == [] and slept == []


def test_limit_caps_matches_processed():
    fetch = _fake_fetch({"2486849": _html("2486849"), "29232": _html("29232")})
    post = _Recorder()
    summary = BF.run_backfill(_tasks("2486849", "29232"), season_code=SEASON,
                              competition_id=COMP, fetch=fetch, post=post,
                              limit=1, sleep_s=0, log=lambda *_: None)
    assert summary["seen"] == 1 and summary["ok"] == 1


def test_integrity_failure_is_skipped_not_posted():
    tampered = _html("2486849").replace("<td class=\"puntos\">11</td>",
                                        "<td class=\"puntos\">999</td>", 1)
    fetch = _fake_fetch({"2486849": tampered})
    post = _Recorder()
    summary = BF.run_backfill(_tasks("2486849"), season_code=SEASON, competition_id=COMP,
                              fetch=fetch, post=post, sleep_s=0, log=lambda *_: None)
    assert summary["skipped"] == 1 and summary["ok"] == 0 and post.calls == []


def test_rate_limit_sleeps_between_matches():
    fetch = _fake_fetch({"2486849": _html("2486849"), "29232": _html("29232")})
    post = _Recorder()
    slept = []
    BF.run_backfill(_tasks("2486849", "29232"), season_code=SEASON, competition_id=COMP,
                    fetch=fetch, post=post, sleep_s=1.5, sleep_fn=slept.append,
                    log=lambda *_: None)
    assert slept == [1.5, 1.5]
