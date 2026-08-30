"""Replaying the missing finalization for matches ingested but never closed.

The 2025-26 gap: half the season carried a full boxscore yet sat SCHEDULED, so
the content engine — which only reads finalized matches — was building every
card from half the league. These pin the rule that makes the repair safe: the
score is DERIVED from the stored team stats and cross-checked, never guessed.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "feb" / "finalize_pending.py"
_spec = importlib.util.spec_from_file_location("finalize_pending", _PATH)
fp = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves annotations through sys.modules, and
# a module loaded by path alone is not there yet.
sys.modules["finalize_pending"] = fp
_spec.loader.exec_module(fp)


def _match(eid="m1", status="SCHEDULED", home="tH", away="tA"):
    return {"external_id": eid, "status": status, "home_team_id": home,
            "away_team_id": away, "season_code": "2025-2026",
            "competition_id": "segunda-feb", "round_number": 12}


def _detail(home_pf=94, away_pf=80, *, home="tH", away="tA", consistent=True):
    return {"team_stats": [
        {"team_external_id": home, "points_for": home_pf,
         "points_against": away_pf if consistent else away_pf + 3},
        {"team_external_id": away, "points_for": away_pf, "points_against": home_pf},
    ]}


class TestScoreDerivation:
    def test_reads_the_score_from_the_stored_team_stats(self):
        assert fp.score_from_team_stats(_match(), _detail()) == (94, 80)

    def test_refuses_when_the_two_rows_disagree(self):
        """Each team row carries both points_for and points_against, so the pair
        is self-checking. A disagreement means the boxscore is unreliable —
        skip it rather than finalize a match on a number we cannot trust."""
        assert fp.score_from_team_stats(_match(), _detail(consistent=False)) is None

    def test_refuses_without_both_teams(self):
        one_side = {"team_stats": [{"team_external_id": "tH", "points_for": 94,
                                    "points_against": 80}]}
        assert fp.score_from_team_stats(_match(), one_side) is None
        assert fp.score_from_team_stats(_match(), {"team_stats": []}) is None


class TestCommand:
    def test_carries_the_score_and_no_invented_periods(self):
        cmd = fp.build_finalize(_match(), 94, 80)
        assert cmd["payload"]["match_external_id"] == "m1"
        assert cmd["payload"]["score_summary"] == {"home_score": 94, "away_score": 80}
        # the stored team stats have no quarters; inventing a split would be a lie
        assert "periods" not in cmd["payload"]["score_summary"]

    def test_command_id_is_deterministic_so_replays_are_idempotent(self):
        a = fp.build_finalize(_match(), 94, 80)["command_id"]
        b = fp.build_finalize(_match(), 94, 80)["command_id"]
        assert a == b
        other = fp.build_finalize(_match(eid="m2"), 94, 80)["command_id"]
        assert other != a

    def test_id_matches_the_ingest_runner_namespace(self):
        """It must collide with the id the original pipeline would have used, so
        this repair replays that command instead of writing beside it."""
        import uuid
        expected = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "feb-score-ingestor-finalize:2025-2026|segunda-feb|m1"))
        assert fp.build_finalize(_match(), 94, 80)["command_id"] == expected


class TestRun:
    def _fake(self, matches, details):
        def get(path):
            if "/search" in path:
                return {"items": matches}
            eid = path.rsplit("/", 1)[-1]
            return details[eid]
        return get

    def test_finalizes_only_what_is_pending(self):
        matches = [_match("m1"), _match("m2", status="FINALIZED"), _match("m3")]
        details = {"m1": _detail(), "m3": _detail(70, 68)}
        sent = []
        stats = fp.run("2025-2026", range(12, 13),
                       get=self._fake(matches, details),
                       post=lambda t, c: sent.append((t, c)) or 200,
                       dry_run=False)
        assert stats.finalized == 2 and stats.already_final == 1
        assert [c["payload"]["score_summary"]["home_score"] for _, c in sent] == [94, 70]

    def test_a_match_without_stats_is_skipped_not_finalized(self):
        matches = [_match("m1")]
        details = {"m1": {"team_stats": []}}
        sent = []
        stats = fp.run("2025-2026", range(12, 13), get=self._fake(matches, details),
                       post=lambda t, c: sent.append(c) or 200, dry_run=False)
        assert stats.finalized == 0 and stats.skipped_no_stats == 1
        assert sent == []

    def test_dry_run_writes_nothing(self):
        matches = [_match("m1")]
        details = {"m1": _detail()}
        calls = []
        stats = fp.run("2025-2026", range(12, 13), get=self._fake(matches, details),
                       post=lambda t, c: calls.append(c) or 200, dry_run=True)
        assert stats.finalized == 1      # counted as it WOULD be finalized
        assert calls == []               # but nothing was sent

    def test_a_failing_post_is_counted_not_swallowed(self):
        matches = [_match("m1")]
        details = {"m1": _detail()}
        stats = fp.run("2025-2026", range(12, 13), get=self._fake(matches, details),
                       post=lambda t, c: 500, dry_run=False)
        assert stats.finalized == 0 and stats.failed == 1
