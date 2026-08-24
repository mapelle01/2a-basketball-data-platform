"""Public-boxscore name resolver: player + team names from Partido.aspx pages.

Proves names resolve from the same public HTML the parser already produces
(any season, no token), deterministically, and that a bad page is isolated.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

from feb_score.application.use_cases.public_name_resolver import PublicBoxscoreNameResolver

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/ingestion/fixtures"

_spec = importlib.util.spec_from_file_location(
    "parse_public_boxscore", ROOT / "scripts" / "feb" / "parse_public_boxscore.py"
)
PPB = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = PPB
_spec.loader.exec_module(PPB)


class _Match:
    def __init__(self, ext):
        self.external_id = ext


class _Repo:
    def __init__(self, ids):
        self._ids = ids

    def search(self, season_code):
        return [_Match(i) for i in self._ids]


def _fetch(mapping):
    def fetch(mid):
        if mid not in mapping:
            raise RuntimeError(f"no fixture for {mid}")
        return mapping[mid]
    return fetch


def _resolver(kind, mapping, ids=None):
    return PublicBoxscoreNameResolver(
        _Repo(ids or list(mapping)), "2025-2026", kind,
        max_workers=2, fetch=_fetch(mapping), parse=PPB.parse_public_boxscore)


def test_resolves_player_names():
    html = (FIX / "partido_2486849.html").read_text(encoding="utf-8")
    names = _resolver("players", {"2486849": html}).resolve("2025-2026")
    assert names, "expected player names"
    assert all(isinstance(v, str) and v for v in names.values())
    assert "1549741" in names  # a known player id from this boxscore


def test_resolves_team_names():
    html = (FIX / "partido_2486849.html").read_text(encoding="utf-8")
    box = PPB.parse_public_boxscore(html, "2486849")
    names = _resolver("teams", {"2486849": html}).resolve("2025-2026")
    assert set(names) == {str(box.home.external_id), str(box.away.external_id)}
    assert names[str(box.home.external_id)] == box.home.name.strip()


def test_old_season_also_resolves():
    html = (FIX / "partido_29232.html").read_text(encoding="utf-8")
    names = _resolver("players", {"29232": html}).resolve("2005-2006")
    assert names and all(v for v in names.values())


def test_bad_page_is_isolated():
    good = (FIX / "partido_2486849.html").read_text(encoding="utf-8")
    r = _resolver("players", {"2486849": good}, ids=["999", "2486849"])  # 999 missing → raises
    names = r.resolve("2025-2026")
    assert "1549741" in names  # the good match still resolved


def test_deterministic_most_frequent_name():
    # same player id with two spellings across matches → most frequent wins
    from feb_score.application.use_cases.public_name_resolver import _pick
    assert _pick(["PEREZ, A", "PEREZ, A", "PEREÑ, A"]) == "PEREZ, A"
    assert _pick(["B", "A"]) == "A"  # tie → lexicographically smallest
    assert _pick([]) is None
