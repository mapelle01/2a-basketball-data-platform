"""FASE 24.1 — Team name resolution from the official FEB calendar.

Offline only: reads the FASE 22.1/22.5 calendar fixtures (ESTE + OESTE) and
checks the deterministic mapping calendar-match -> (home/away team id) -> name.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "backfill_catalog", ROOT / "scripts" / "feb" / "backfill_catalog.py"
)
B = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = B
_spec.loader.exec_module(B)

FIXTURES = ROOT / "tests" / "ingestion" / "fixtures"
ESTE = (FIXTURES / "calendario_jornadas_2025_2026.html").read_text(encoding="utf-8")
OESTE = (FIXTURES / "calendario_oeste_2025_2026.html").read_text(encoding="utf-8")

SEASON = "2025-2026"


def _matches_from_rows(*rows):
    return [tuple(r) for r in rows]


def test_team_names_resolved_from_calendar():
    # calendar match 2486849: SPANISH BASKETBALL ACADEMY (home) - LOBE HUESCA (away)
    matches = _matches_from_rows(
        ("2486849", "T-A", "T-B"),
        ("2486850", "T-C", "T-D"),
        ("2487759", "T-E", "T-F"),
    )
    resolved = B.resolve_team_names_from_calendar(
        SEASON, matches, {"ESTE": ESTE, "OESTE": OESTE}
    )
    assert resolved["T-A"] == "SPANISH BASKETBALL ACADEMY"
    assert resolved["T-B"] == "LOBE HUESCA LA MAGIA"
    assert resolved["T-E"] == "UEMC BALONCESTO VALLADOLID"
    assert resolved["T-F"] == "CLUB BALONCESTO TOLEDO BASKET"


def test_unmatched_matches_are_ignored():
    resolved = B.resolve_team_names_from_calendar(
        SEASON, [("999999", "TX", "TY")], {"ESTE": ESTE}
    )
    assert resolved == {}


def test_empty_groups_yield_empty_map():
    assert B.resolve_team_names_from_calendar(SEASON, [("2486849", "T-A", "T-B")], {}) == {}


def test_deterministic_majority_with_tie_break():
    # team T-A appears twice in ESTE calendar; give a conflicting candidate once
    matches = _matches_from_rows(
        ("2486849", "T-A", "T-B"),
        ("2486850", "T-A", "T-D"),  # T-A also home in 2486850 (HOMS U.E.MATARÓ)
        ("2486851", "T-B", "T-A"),
    )
    first = B.resolve_team_names_from_calendar(SEASON, matches, {"ESTE": ESTE})
    second = B.resolve_team_names_from_calendar(SEASON, matches, {"ESTE": ESTE})
    assert first == second  # deterministic
    # every resolved team has exactly one name
    assert all(isinstance(v, str) and v for v in first.values())