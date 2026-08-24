"""Public FEB boxscore parser — offline tests against real fixtures.

No network, no token: reads saved ``Partido.aspx`` pages (a 2025-26 match and a
2005-06 one) to prove the parser extracts the full per-player boxscore — incl.
shooting splits, official valoración, +/- and quarters — across eras. The key
correctness invariant is that the players' points sum to the team score.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/ingestion/fixtures"

_spec = importlib.util.spec_from_file_location(
    "parse_public_boxscore", ROOT / "scripts" / "feb" / "parse_public_boxscore.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = M
_spec.loader.exec_module(M)


def _box(match_id: str):
    html = (FIX / f"partido_{match_id}.html").read_text(encoding="utf-8")
    return M.parse_public_boxscore(html, match_id)


class TestRecentMatch:
    def setup_method(self):
        self.b = _box("2486849")  # 2025-26

    def test_scoreboard(self):
        assert self.b.home.name == "SPANISH BASKETBALL ACADEMY"
        assert self.b.home.external_id == "981514" and self.b.home.score == 78
        assert self.b.away.name == "LOBE HUESCA LA MAGIA"
        assert self.b.away.external_id == "981281" and self.b.away.score == 66

    def test_quarters_sum_to_score(self):
        assert self.b.home.quarters == (22, 17, 28, 11)
        assert sum(self.b.home.quarters) == self.b.home.score
        assert sum(self.b.away.quarters) == self.b.away.score

    def test_full_player_line(self):
        p = next(p for p in self.b.players if p.player_external_id == "1549741")
        assert p.name == "ARQUES LOPEZ, EDUARD"
        assert p.team_external_id == "981514"           # i= is the team id
        assert (p.points, p.assists, p.rebounds_total) == (11, 1, 4)
        assert p.rebounds_offensive == 1 and p.rebounds_defensive == 3
        assert (p.two_points.made, p.two_points.attempted) == (2, 5)
        assert (p.three_points.made, p.three_points.attempted) == (2, 4)
        assert (p.free_throws.made, p.free_throws.attempted) == (1, 4)
        assert (p.field_goals.made, p.field_goals.attempted) == (4, 9)
        assert p.valoracion == 8 and p.plus_minus == -10
        assert p.minutes == pytest.approx(22.8, abs=0.05)
        assert p.starter is False

    def test_shooting_pct_helper(self):
        p = next(p for p in self.b.players if p.player_external_id == "1549741")
        assert p.three_points.pct == 50.0
        assert self.b.players[0].__class__ is M.PublicPlayerLine


class TestOldMatch:
    def setup_method(self):
        self.b = _box("29232")  # 2005-06 (LEB Plata era) — deep history, full data

    def test_parses_with_full_data(self):
        assert self.b.home.score == 87 and self.b.away.score == 75
        assert len(self.b.players) == 20
        # shooting + valoración present even in an old match
        assert any(p.three_points.attempted > 0 for p in self.b.players)
        assert any(p.valoracion != 0 for p in self.b.players)
        assert any(p.starter for p in self.b.players)


@pytest.mark.parametrize("mid", ["2486849", "29232"])
def test_points_sum_to_team_score(mid):
    """The core integrity invariant across eras."""
    b = _box(mid)
    for team in (b.home, b.away):
        total = sum(p.points for p in b.players_of(team.external_id))
        assert total == team.score, f"{team.name}: Σpts {total} != {team.score}"


def test_every_player_belongs_to_a_team():
    b = _box("2486849")
    ids = {b.home.external_id, b.away.external_id}
    assert all(p.team_external_id in ids for p in b.players)


def test_rejects_non_boxscore_html():
    with pytest.raises(M.ParseError):
        M.parse_public_boxscore("<html><body>no match here</body></html>", "0")
