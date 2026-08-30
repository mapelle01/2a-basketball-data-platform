"""The one destructive script in the repo, so its guards are the test.

Deploy smoke fixtures accumulated inside a real season — one per production
deploy. Removing them is fine; removing anything else is not, so the selection
must be narrow and a match carrying stats must be untouchable.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_PATH = (pathlib.Path(__file__).resolve().parents[2]
         / "scripts" / "maintenance" / "purge_smoke_matches.py")
_spec = importlib.util.spec_from_file_location("purge_smoke_matches", _PATH)
psm = importlib.util.module_from_spec(_spec)
sys.modules["purge_smoke_matches"] = psm
_spec.loader.exec_module(psm)


class FakeCursor:
    """Records the SQL it is given and replays canned rows."""

    def __init__(self, smoke_rows, stats_rows=()):
        self._smoke = smoke_rows
        self._stats = stats_rows
        self._result = []
        self.executed = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FROM matches m" in sql:
            self._result = list(self._smoke)
        elif "match_player_stats" in sql:
            wanted = set(params[0])
            self._result = [(e,) for e in self._stats if e in wanted]
        elif sql.startswith("DELETE"):
            self.rowcount = len(params[0])
            self._result = []

    def fetchall(self):
        return self._result


class TestSelection:
    def test_requires_both_the_competition_and_the_prefix(self):
        """A prefix alone could catch a real external id; a competition alone is
        one typo from a real one. Both conditions must be in the query."""
        cur = FakeCursor([])
        psm.find_smoke(cur)
        sql, params = cur.executed[0]
        assert "competition_id = %s" in sql and "external_id LIKE %s" in sql
        assert params == ("smoke-comp", "smoke-%")

    def test_returns_what_it_found(self):
        rows = [("smoke-1", "2025-2026", "SCHEDULED"), ("smoke-2", "2025-2026", "SCHEDULED")]
        assert psm.find_smoke(FakeCursor(rows)) == rows


class TestStatsGuard:
    def test_a_match_with_stats_is_reported_as_protected(self):
        cur = FakeCursor([], stats_rows=["smoke-2"])
        assert psm.with_stats(cur, ["smoke-1", "smoke-2"]) == ["smoke-2"]

    def test_no_ids_means_no_query(self):
        cur = FakeCursor([])
        assert psm.with_stats(cur, []) == []
        assert cur.executed == []          # never asks the database for nothing


class TestConstants:
    def test_targets_only_the_smoke_competition(self):
        assert psm.SMOKE_COMPETITION == "smoke-comp"
        assert psm.SMOKE_PREFIX == "smoke-"

    def test_delete_is_scoped_by_explicit_ids_not_by_a_pattern(self):
        """The delete takes the vetted id list, so anything the stats guard
        removed from that list cannot be caught by a stray LIKE."""
        assert "= ANY(%s)" in psm._DELETE
        assert "LIKE" not in psm._DELETE


class TestSmokeScriptItself:
    def test_the_smoke_test_no_longer_writes_into_a_real_season(self):
        """The root cause: the fixture was created in season 2025-2026."""
        sh = (pathlib.Path(__file__).resolve().parents[2]
              / "scripts" / "staging_smoke.sh").read_text()
        assert 'SMOKE_SEASON="0000-0000"' in sh
        # the PAYLOAD must carry the variable, not a real season literal
        assert r'\"season_code\":\"${SMOKE_SEASON}\"' in sh
        assert r'\"season_code\":\"2025-2026\"' not in sh
