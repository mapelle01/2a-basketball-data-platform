"""FASE 25 — Auto-ingest orchestrator unit tests (offline, no network).

Covers ``_active_rounds`` selection (daily mode window) using synthetic
calendar data built through ``discover_matches`` MatchRefs. No FEB token, no API
key, no production POST.
"""

from __future__ import annotations

import importlib.util
import sys as _sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts" / "feb") not in _sys.path:
    _sys.path.insert(0, str(ROOT / "scripts" / "feb"))

_spec = importlib.util.spec_from_file_location(
    "run_auto_ingest", ROOT / "scripts" / "feb" / "run_auto_ingest.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules["run_auto_ingest"] = M
_spec.loader.exec_module(M)


def _ref(ext: int, round_number: int, scheduled_at: str):
    return M.DM.MatchRef(
        external_id=ext,
        round_number=round_number,
        scheduled_at=scheduled_at,
        home_team="HOME",
        away_team="AWAY",
        source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={ext}",
    )


def _calendar(*round_dates):
    """{round_number: [MatchRef]} from (round_number, iso_date) tuples."""
    out = {}
    for rn, iso in round_dates:
        out.setdefault(rn, []).append(_ref(100 + rn, rn, iso))
    return out


def test_active_rounds_picks_current_and_upcoming():
    today = date(2026, 1, 15)
    cal = _calendar(
        (1, "2025-10-04T00:00:00+01:00"),
        (2, "2025-10-11T00:00:00+01:00"),
        (3, "2025-10-18T00:00:00+01:00"),
        (4, "2025-10-25T00:00:00+01:00"),
        (5, "2025-11-01T00:00:00+01:00"),
        (6, "2026-01-17T00:00:00+01:00"),
        (7, "2026-01-25T00:00:00+01:00"),
    )
    active = M._active_rounds(cal, today)
    assert 6 in active
    assert 7 in active
    assert 1 not in active


def test_active_rounds_empty_when_season_not_started():
    today = date(2026, 8, 1)  # between seasons
    cal = _calendar(
        (1, "2026-10-03T00:00:00+01:00"),
        (2, "2026-10-10T00:00:00+01:00"),
    )
    assert M._active_rounds(cal, today) == []


def test_active_rounds_sorted():
    today = date(2026, 1, 15)
    cal = _calendar(
        (8, "2026-01-25T00:00:00+01:00"),
        (7, "2026-01-20T00:00:00+01:00"),
        (6, "2026-01-17T00:00:00+01:00"),
    )
    assert M._active_rounds(cal, today) == [6, 7, 8]


def test_post_backfill_builds_url_and_bearer(monkeypatch):
    calls = {}

    class _Resp:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def read(self):
            return b'{"ok":true}'

    def _fake_open(req, timeout=0):
        calls["url"] = req.full_url
        calls["method"] = req.get_method()
        calls["auth"] = req.get_header("Authorization")
        calls["body"] = req.data.decode("utf-8")
        return _Resp()

    monkeypatch.setattr(M.urllib.request, "urlopen", _fake_open)
    res = M._post_backfill("2025-2026", "https://api.example", "abcd")
    assert res["status"] == 200
    assert calls["url"] == "https://api.example/v1/commands/backfill_catalog"
    assert calls["auth"] == "Bearer abcd"
    assert '"entity": "both"' in calls["body"]
    assert '"dry_run": false' in calls["body"]